# cost_estimator/scripts/provision.py
import os, json, time, ipaddress
from pathlib import Path
from typing import Dict, Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from flask import Blueprint, request, jsonify

provision_bp = Blueprint("provision", __name__)

TARGET_REGION_CODE = os.getenv("TARGET_REGION_CODE", "us-east-1")
AWS_PROFILE_NAME   = os.getenv("AWS_PROFILE") or os.getenv("CLOUD_MIGRATION_AWS_PROFILE")

STATE_DIR = Path(__file__).resolve().parents[1] / "data" / "provision"
STATE_DIR.mkdir(parents=True, exist_ok=True)

def _session():
    if AWS_PROFILE_NAME:
        return boto3.session.Session(profile_name=AWS_PROFILE_NAME)
    return boto3.session.Session()

def _ec2(region: str):
    return _session().client("ec2", region_name=region, config=Config(retries={"max_attempts": 10,"mode":"standard"}))

def _state_file(region: str) -> Path:
    return STATE_DIR / f"state_{region}.json"

def _read_state(region: str) -> Dict[str, Any]:
    p = _state_file(region)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"region": region, "stack": {}, "instances": []}

def _write_state(region: str, data: Dict[str, Any]):
    _state_file(region).write_text(json.dumps(data, indent=2), encoding="utf-8")

def _is_arm64(itype: str) -> bool:
    fam = (itype or "").split(".")[0].lower()
    armish = ("a1","c6g","c6gd","c6gn","c7g","c7gd","c7gn","c8g","c8gd",
              "m6g","m6gd","m7g","m8g","r6g","r7g","r8g","t4g","x2gd","i8g","g5g")
    return any(fam.startswith(p) for p in armish)

def _latest_al2023_ami(ec2, arm: bool) -> Optional[str]:
    # Amazon Linux 2023; x86_64 or arm64
    arch = "arm64" if arm else "x86_64"
    resp = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": [f"al2023-ami-*-kernel-6.1-{arch}"]},
            {"Name": "state", "Values": ["available"]},
        ]
    )
    images = resp.get("Images", [])
    if not images:
        return None
    images.sort(key=lambda im: im.get("CreationDate",""), reverse=True)
    return images[0]["ImageId"]

def _ensure_stack(region: str) -> Dict[str, str]:
    """
    Create a tiny 'cmtool' VPC stack we fully own (so we can delete everything).
    VPC 10.0.0.0/16, one public subnet 10.0.1.0/24, IGW, route table + route, SG (22/80/443 inbound).
    Idempotent: if exists in state, verify it still exists; otherwise (re)create.
    """
    ec2 = _ec2(region)
    st = _read_state(region)

    # If we already have a recorded stack, verify it exists
    s = st.get("stack") or {}
    if s.get("vpc_id"):
        try:
            ec2.describe_vpcs(VpcIds=[s["vpc_id"]])
            # Quick check SG + Subnet still exist; if not, fall through to recreate
            ec2.describe_subnets(SubnetIds=[s["subnet_id"]])
            ec2.describe_security_groups(GroupIds=[s["sg_id"]])
            return s
        except ClientError:
            pass  # fall through to recreate

    # Create a new VPC we own
    vpc = ec2.create_vpc(
        CidrBlock="10.0.0.0/16",
        TagSpecifications=[{"ResourceType":"vpc","Tags":[{"Key":"Name","Value":"cmtool-vpc"},{"Key":"cmtool","Value":"true"}]}]
    )["Vpc"]
    vpc_id = vpc["VpcId"]
    # DNS attributes
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})

    # Pick first AZ
    azs = ec2.describe_availability_zones(Filters=[{"Name":"region-name","Values":[region]}]).get("AvailabilityZones",[])
    az_name = azs[0]["ZoneName"] if azs else None

    # Subnet (public)
    subnet = ec2.create_subnet(
        VpcId=vpc_id,
        CidrBlock="10.0.1.0/24",
        AvailabilityZone=az_name,
        TagSpecifications=[{"ResourceType":"subnet","Tags":[{"Key":"Name","Value":"cmtool-public-subnet"},{"Key":"cmtool","Value":"true"}]}]
    )["Subnet"]
    subnet_id = subnet["SubnetId"]
    ec2.modify_subnet_attribute(SubnetId=subnet_id, MapPublicIpOnLaunch={"Value": True})

    # Internet Gateway + attach
    igw = ec2.create_internet_gateway(
        TagSpecifications=[{"ResourceType":"internet-gateway","Tags":[{"Key":"Name","Value":"cmtool-igw"},{"Key":"cmtool","Value":"true"}]}]
    )["InternetGateway"]
    igw_id = igw["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    # Route table + default route + association
    rtb = ec2.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[{"ResourceType":"route-table","Tags":[{"Key":"Name","Value":"cmtool-rtb"},{"Key":"cmtool","Value":"true"}]}]
    )["RouteTable"]
    rtb_id = rtb["RouteTableId"]
    try:
        ec2.create_route(RouteTableId=rtb_id, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw_id)
    except ClientError:
        pass
    assoc = ec2.associate_route_table(RouteTableId=rtb_id, SubnetId=subnet_id)
    assoc_id = assoc["AssociationId"]

    # Security Group
    sg = ec2.create_security_group(
        GroupName="cmtool-sg",
        Description="cmtool default sg",
        VpcId=vpc_id,
        TagSpecifications=[{"ResourceType":"security-group","Tags":[{"Key":"Name","Value":"cmtool-sg"},{"Key":"cmtool","Value":"true"}]}]
    )
    sg_id = sg["GroupId"]
    # Allow SSH(22) only from anywhere (you can narrow to your IP), and 80/443
    ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[
        {"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"SSH"}]},
        {"IpProtocol":"tcp","FromPort":80,"ToPort":80,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"HTTP"}]},
        {"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"HTTPS"}]},
    ])
    ec2.authorize_security_group_egress(GroupId=sg_id, IpPermissions=[
        {"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"All egress"}]}
    ])

    stack = {
        "vpc_id": vpc_id,
        "subnet_id": subnet_id,
        "igw_id": igw_id,
        "route_table_id": rtb_id,
        "route_assoc_id": assoc_id,
        "sg_id": sg_id,
        "created": int(time.time())
    }
    st["stack"] = stack
    _write_state(region, st)
    return stack

def _terminate_instance(ec2, instance_id: str):
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
    except ClientError as e:
        if e.response.get("Error",{}).get("Code") not in ("InvalidInstanceID.NotFound",):
            raise

def _teardown_stack(region: str):
    ec2 = _ec2(region)
    st = _read_state(region)

    # 1) Terminate tracked instances
    for inst in st.get("instances", []):
        _terminate_instance(ec2, inst.get("instance_id"))

    # 2) Delete SG, RTB (and association), detach+delete IGW, delete Subnet, then VPC
    s = st.get("stack") or {}
    sg_id = s.get("sg_id")
    rtb_id = s.get("route_table_id")
    assoc_id = s.get("route_assoc_id")
    igw_id = s.get("igw_id")
    subnet_id = s.get("subnet_id")
    vpc_id = s.get("vpc_id")

    def _safe(fn, **kw):
        try:
            fn(**kw)
        except ClientError as e:
            # Ignore "not found" style errors
            pass

    # Wait for instances to terminate (best effort)
    if st.get("instances"):
        try:
            waiter = ec2.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=[i["instance_id"] for i in st["instances"] if i.get("instance_id")], WaiterConfig={"Delay": 5,"MaxAttempts": 30})
        except ClientError:
            pass

    if sg_id:
        _safe(ec2.delete_security_group, GroupId=sg_id)

    if assoc_id:
        _safe(ec2.disassociate_route_table, AssociationId=assoc_id)
    if rtb_id:
        # also try removing default route (ignore if not there)
        try:
            ec2.delete_route(RouteTableId=rtb_id, DestinationCidrBlock="0.0.0.0/0")
        except ClientError:
            pass
        _safe(ec2.delete_route_table, RouteTableId=rtb_id)

    if igw_id and vpc_id:
        _safe(ec2.detach_internet_gateway, InternetGatewayId=igw_id, VpcId=vpc_id)
        _safe(ec2.delete_internet_gateway, InternetGatewayId=igw_id)

    if subnet_id:
        _safe(ec2.delete_subnet, SubnetId=subnet_id)

    if vpc_id:
        _safe(ec2.delete_vpc, VpcId=vpc_id)

    # Reset state
    st["stack"] = {}
    st["instances"] = []
    _write_state(region, st)

@provision_bp.route("/provision/state", methods=["GET"])
def provision_state():
    region = request.args.get("region", TARGET_REGION_CODE)
    return jsonify(_read_state(region))

@provision_bp.route("/provision/instance", methods=["POST"])
def provision_instance():
    """
    Body: { "instance_type": "t3.medium", "region": "us-east-1" }
    Creates (or reuses) a small cmtool VPC stack and runs one instance.
    Returns instance id, public IP (if available), and stack ids.
    """
    body = request.get_json(force=True, silent=True) or {}
    itype = body.get("instance_type")
    if not itype or not isinstance(itype, str):
        return jsonify({"error":"Provide {\"instance_type\":\"t3.micro\"}"}), 400
    region = body.get("region") or TARGET_REGION_CODE

    ec2 = _ec2(region)
    stack = _ensure_stack(region)
    arm = _is_arm64(itype)
    ami = _latest_al2023_ami(ec2, arm)
    if not ami:
        return jsonify({"error":"Could not find a suitable Amazon Linux 2023 AMI"}), 500

    # Create instance
    run = ec2.run_instances(
        ImageId=ami,
        InstanceType=itype,
        MinCount=1, MaxCount=1,
        NetworkInterfaces=[{
            "SubnetId": stack["subnet_id"],
            "AssociatePublicIpAddress": True,
            "DeviceIndex": 0,
            "Groups": [stack["sg_id"]],
        }],
        TagSpecifications=[{
            "ResourceType":"instance",
            "Tags":[{"Key":"Name","Value":f"cmtool-{int(time.time())}"},{"Key":"cmtool","Value":"true"}]
        }],
        MetadataOptions={"HttpTokens": "required"}  # more secure IMDSv2
    )
    inst = run["Instances"][0]
    instance_id = inst["InstanceId"]

    # Record in state
    st = _read_state(region)
    st.setdefault("instances", []).append({
        "instance_id": instance_id,
        "instance_type": itype,
        "created": int(time.time())
    })
    _write_state(region, st)

    # Try to fetch a public IP quickly (it may be pending)
    desc = ec2.describe_instances(InstanceIds=[instance_id])
    net = (((desc.get("Reservations") or [])[0].get("Instances") or [])[0].get("NetworkInterfaces") or [])
    public_ip = None
    if net and net[0].get("Association"):
        public_ip = net[0]["Association"].get("PublicIp")

    return jsonify({
        "region": region,
        "instance_id": instance_id,
        "instance_type": itype,
        "public_ip": public_ip,
        "ami": ami,
        "stack": stack
    })

@provision_bp.route("/provision/instance/<instance_id>", methods=["DELETE"])
def delete_instance(instance_id: str):
    region = request.args.get("region", TARGET_REGION_CODE)
    ec2 = _ec2(region)
    _terminate_instance(ec2, instance_id)

    # remove from state if present
    st = _read_state(region)
    st["instances"] = [i for i in st.get("instances", []) if i.get("instance_id") != instance_id]
    _write_state(region, st)
    return jsonify({"ok": True, "terminated": instance_id, "region": region})

@provision_bp.route("/provision/teardown", methods=["POST"])
def teardown_all():
    region = request.args.get("region", TARGET_REGION_CODE)
    _teardown_stack(region)
    return jsonify({"ok": True, "region": region, "message": "All cmtool resources deleted"})
