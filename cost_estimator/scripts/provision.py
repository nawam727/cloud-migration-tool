# cost_estimator/scripts/provision_aws.py
import os
import time
import uuid
from typing import Dict, Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from flask import Blueprint, request, jsonify

provision_bp = Blueprint("provision", __name__)

AWS_PROFILE_NAME = os.getenv("AWS_PROFILE") or os.getenv("CLOUD_MIGRATION_AWS_PROFILE")
DEFAULT_REGION = os.getenv("TARGET_REGION_CODE", "us-east-1")

STACK_TAG_KEY = "CloudMigStack"       # used on all created resources
NAME_TAG_KEY  = "Name"

# in-memory stack registry (also do tag-based discovery on destroy)
_STACKS: Dict[str, Dict[str, Any]] = {}

def _session():
    if AWS_PROFILE_NAME:
        return boto3.session.Session(profile_name=AWS_PROFILE_NAME)
    return boto3.session.Session()

def ec2(region: str):
    return _session().client("ec2", region_name=region, config=Config(
        retries={"max_attempts": 10, "mode": "standard"}
    ))

def _tag_spec(resource: str, stack_id: str, name: str):
    return [{
        "ResourceType": resource,
        "Tags": [
            {"Key": STACK_TAG_KEY, "Value": stack_id},
            {"Key": NAME_TAG_KEY,  "Value": name},
        ],
    }]

def _ignore_duplicate_rule(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") in ("InvalidPermission.Duplicate",)

def _ignore_not_found(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") in (
        "InvalidGroup.NotFound", "InvalidVpcID.NotFound", "InvalidRouteTableID.NotFound",
        "InvalidSubnetID.NotFound", "InvalidInternetGatewayID.NotFound",
        "InvalidAssociationID.NotFound", "InvalidInstanceID.NotFound"
    )

# ---------------------------
# Discover / Create networking
# ---------------------------
def _find_default_vpc(cli, region: str) -> Optional[str]:
    resp = cli.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    vpcs = resp.get("Vpcs", [])
    return vpcs[0]["VpcId"] if vpcs else None

def _get_default_subnet(cli, vpc_id: str) -> Optional[str]:
    # any default-for-az subnet within the default VPC
    resp = cli.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    for sn in resp.get("Subnets", []):
        return sn["SubnetId"]  # pick first
    return None

def _create_min_vpc(cli, stack_id: str, region: str) -> Dict[str, Any]:
    # VPC
    v = cli.create_vpc(CidrBlock="10.0.0.0/16", TagSpecifications=_tag_spec("vpc", stack_id, f"mig-vpc-{stack_id[:8]}"))
    vpc_id = v["Vpc"]["VpcId"]
    cli.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
    cli.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})

    # Subnet
    sn = cli.create_subnet(
        VpcId=vpc_id,
        CidrBlock="10.0.1.0/24",
        TagSpecifications=_tag_spec("subnet", stack_id, f"mig-subnet-{stack_id[:8]}"),
    )
    subnet_id = sn["Subnet"]["SubnetId"]
    cli.modify_subnet_attribute(SubnetId=subnet_id, MapPublicIpOnLaunch={"Value": True})

    # IGW
    igw = cli.create_internet_gateway(TagSpecifications=_tag_spec("internet-gateway", stack_id, f"mig-igw-{stack_id[:8]}"))
    igw_id = igw["InternetGateway"]["InternetGatewayId"]
    cli.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    # Route table + default route
    rt = cli.create_route_table(VpcId=vpc_id, TagSpecifications=_tag_spec("route-table", stack_id, f"mig-rt-{stack_id[:8]}"))
    rt_id = rt["RouteTable"]["RouteTableId"]
    try:
        cli.create_route(RouteTableId=rt_id, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw_id)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "RouteAlreadyExists":
            raise
    cli.associate_route_table(RouteTableId=rt_id, SubnetId=subnet_id)

    return {
        "created_vpc": True,
        "vpc_id": vpc_id,
        "subnet_id": subnet_id,
        "igw_id": igw_id,
        "route_table_id": rt_id,
    }

def _get_or_create_sg(cli, vpc_id: str, stack_id: str) -> Dict[str, Any]:
    # try find SG by stack tag
    resp = cli.describe_security_groups(
        Filters=[
            {"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )
    if resp.get("SecurityGroups"):
        sg_id = resp["SecurityGroups"][0]["GroupId"]
        created = False
    else:
        sg = cli.create_security_group(
            GroupName=f"mig-sg-{stack_id[:8]}",
            Description=f"Mig SG {stack_id}",
            VpcId=vpc_id,
            TagSpecifications=_tag_spec("security-group", stack_id, f"mig-sg-{stack_id[:8]}"),
        )
        sg_id = sg["GroupId"]
        created = True

    # egress: allow all
    try:
        cli.authorize_security_group_egress(
            GroupId=sg_id,
            IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
        )
    except ClientError as e:
        if not _ignore_duplicate_rule(e):
            raise

    # ingress: SSH (22)
    try:
        cli.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        )
    except ClientError as e:
        if not _ignore_duplicate_rule(e):
            raise

    return {"security_group_id": sg_id, "created_sg": created}

# ---------------------------
# Instance create / status
# ---------------------------
def _run_instance(cli, region: str, stack_id: str, instance_type: str, subnet_id: str, sg_id: str,
                  tag_name: str, volume_gb: int) -> Dict[str, Any]:
    resp = cli.run_instances(
        MinCount=1, MaxCount=1,
        ImageId=_pick_ami(cli, region),
        InstanceType=instance_type,
        NetworkInterfaces=[{
            "AssociatePublicIpAddress": True,
            "DeviceIndex": 0,
            "SubnetId": subnet_id,
            "Groups": [sg_id],
        }],
        BlockDeviceMappings=[{
            "DeviceName": "/dev/xvda",
            "Ebs": {"VolumeSize": int(volume_gb or 20), "VolumeType": "gp3", "DeleteOnTermination": True},
        }],
        TagSpecifications=[
            *_tag_spec("instance", stack_id, tag_name or f"mig-instance-{stack_id[:8]}"),
            *_tag_spec("volume",   stack_id, f"mig-vol-{stack_id[:8]}"),
            *_tag_spec("network-interface", stack_id, f"mig-eni-{stack_id[:8]}"),
        ]
    )
    inst = resp["Instances"][0]
    inst_id = inst["InstanceId"]
    cli.get_waiter("instance_running").wait(InstanceIds=[inst_id])
    time.sleep(1.0)
    di = cli.describe_instances(InstanceIds=[inst_id])
    i = di["Reservations"][0]["Instances"][0]
    return {
        "id": inst_id,
        "type": i.get("InstanceType"),
        "state": i.get("State", {}).get("Name"),
        "public_ip": i.get("PublicIpAddress"),
    }

def _pick_ami(cli, region: str) -> str:
    owners = ["137112412989", "amazon"]  # Amazon
    for name in ["al2023-ami-*-x86_64", "amzn2-ami-hvm-*-x86_64-gp2"]:
        resp = cli.describe_images(
            Owners=owners,
            Filters=[{"Name": "name", "Values": [name]}, {"Name": "state", "Values": ["available"]}],
        )
        imgs = sorted(resp.get("Images", []), key=lambda x: x.get("CreationDate", ""), reverse=True)
        if imgs:
            return imgs[0]["ImageId"]
    r = cli.describe_images(Owners=["amazon"], Filters=[{"Name": "architecture", "Values": ["x86_64"]}], MaxResults=1)
    return r["Images"][0]["ImageId"]

# ---------------------------
# Destroy helpers (idempotent)
# ---------------------------
def _terminate_instances_by_tag(cli, stack_id: str):
    resp = cli.describe_instances(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}])
    ids = []
    for res in resp.get("Reservations", []):
        for inst in res.get("Instances", []):
            state = inst.get("State", {}).get("Name")
            if state not in ("shutting-down", "terminated"):
                ids.append(inst["InstanceId"])
    if ids:
        cli.terminate_instances(InstanceIds=ids)
        try:
            cli.get_waiter("instance_terminated").wait(InstanceIds=ids)
        except Exception:
            pass

def _disassociate_and_delete_rt(cli, rt_id: str):
    try:
        info = cli.describe_route_tables(RouteTableIds=[rt_id])["RouteTables"][0]
    except ClientError as e:
        if _ignore_not_found(e): return
        raise
    for assoc in info.get("Associations", []):
        if assoc.get("Main"):
            continue
        assoc_id = assoc.get("RouteTableAssociationId")
        if assoc_id:
            try:
                cli.disassociate_route_table(AssociationId=assoc_id)
            except ClientError as e:
                if not _ignore_not_found(e): raise
    try:
        cli.delete_route(RouteTableId=rt_id, DestinationCidrBlock="0.0.0.0/0")
    except ClientError:
        pass
    try:
        cli.delete_route_table(RouteTableId=rt_id)
    except ClientError as e:
        if not _ignore_not_found(e): raise

def _delete_sg(cli, sg_id: str):
    for _ in range(5):
        try:
            cli.delete_security_group(GroupId=sg_id)
            return
        except ClientError as e:
            if _ignore_not_found(e): return
            if e.response.get("Error", {}).get("Code") == "DependencyViolation":
                time.sleep(2.0)
                continue
            raise

def _detach_delete_igw(cli, vpc_id: str, igw_id: str):
    try:
        cli.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
    except ClientError as e:
        if not _ignore_not_found(e): raise
    try:
        cli.delete_internet_gateway(InternetGatewayId=igw_id)
    except ClientError as e:
        if not _ignore_not_found(e): raise

def _delete_subnet(cli, subnet_id: str):
    for _ in range(5):
        try:
            cli.delete_subnet(SubnetId=subnet_id)
            return
        except ClientError as e:
            if _ignore_not_found(e): return
            if e.response.get("Error", {}).get("Code") == "DependencyViolation":
                time.sleep(2.0)
                continue
            raise

def _delete_vpc(cli, vpc_id: str):
    for _ in range(5):
        try:
            cli.delete_vpc(VpcId=vpc_id)
            return
        except ClientError as e:
            if _ignore_not_found(e): return
            if e.response.get("Error", {}).get("Code") == "DependencyViolation":
                time.sleep(2.0)
                continue
            raise

def _discover_network_by_tag(cli, stack_id: str) -> Dict[str, Optional[str]]:
    out = {"vpc_id": None, "subnet_id": None, "security_group_id": None, "igw_id": None, "route_table_id": None}
    vpcs = cli.describe_vpcs(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}]).get("Vpcs", [])
    if vpcs: out["vpc_id"] = vpcs[0]["VpcId"]
    resp = cli.describe_subnets(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}])
    if resp.get("Subnets"): out["subnet_id"] = resp["Subnets"][0]["SubnetId"]
    resp = cli.describe_security_groups(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}])
    if resp.get("SecurityGroups"): out["security_group_id"] = resp["SecurityGroups"][0]["GroupId"]
    resp = cli.describe_internet_gateways(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}])
    if resp.get("InternetGateways"): out["igw_id"] = resp["InternetGateways"][0]["InternetGatewayId"]
    resp = cli.describe_route_tables(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}])
    if resp.get("RouteTables"): out["route_table_id"] = resp["RouteTables"][0]["RouteTableId"]
    return out

def _destroy_stack(cli, region: str, stack_id: str, network: Dict[str, Any]):
    _terminate_instances_by_tag(cli, stack_id)
    if network.get("security_group_id"):
        _delete_sg(cli, network["security_group_id"])
    if network.get("created_vpc"):
        vpc_id = network.get("vpc_id")
        if network.get("route_table_id"):
            _disassociate_and_delete_rt(cli, network["route_table_id"])
        if network.get("igw_id") and vpc_id:
            _detach_delete_igw(cli, vpc_id, network["igw_id"])
        if network.get("subnet_id"):
            _delete_subnet(cli, network["subnet_id"])
        if vpc_id:
            _delete_vpc(cli, vpc_id)

# ---------------------------
# Routes
# ---------------------------
@provision_bp.route("/provision/create", methods=["POST"])
def provision_create():
    body = request.get_json(force=True, silent=True) or {}
    region = body.get("region") or DEFAULT_REGION
    itype  = (
        body.get("type")
        or body.get("instance_type")
        or body.get("InstanceType")
        or request.args.get("type")
        or request.args.get("instance_type")
    )
    vol_gb = int(body.get("volume_gb") or 20)
    tag    = body.get("tag_name") or "demo-instance"

    if not itype or not str(itype).strip():
        return jsonify({"error": "Missing instance type (field 'type' or 'instance_type')"}), 400

    cli = ec2(region)
    stack_id = str(uuid.uuid4())

    # 1) choose networking
    default_vpc_id = _find_default_vpc(cli, region)
    if default_vpc_id:
        subnet_id = _get_default_subnet(cli, default_vpc_id)
        if not subnet_id:
            net = _create_min_vpc(cli, stack_id, region)
        else:
            net = {"created_vpc": False, "vpc_id": default_vpc_id, "subnet_id": subnet_id,
                   "igw_id": None, "route_table_id": None}
    else:
        net = _create_min_vpc(cli, stack_id, region)

    # 2) SG
    sg = _get_or_create_sg(cli, net["vpc_id"], stack_id)
    net.update(sg)

    # 3) Run instance
    inst = _run_instance(cli, region, stack_id, itype, net["subnet_id"], net["security_group_id"], tag, vol_gb)

    record = {"stack_id": stack_id, "region": region, "instance": inst, "network": net, "ts": int(time.time())}
    _STACKS[stack_id] = record
    return jsonify(record)

@provision_bp.route("/provision/status")
def provision_status():
    region = request.args.get("region") or DEFAULT_REGION
    stack_id = request.args.get("stack_id")
    if not stack_id:
        return jsonify({"error": "Missing stack_id"}), 400

    record = _STACKS.get(stack_id, {"stack_id": stack_id, "region": region})
    cli = ec2(region)
    desc = cli.describe_instances(Filters=[{"Name": f"tag:{STACK_TAG_KEY}", "Values": [stack_id]}])
    states = []
    for res in desc.get("Reservations", []):
        for i in res.get("Instances", []):
            states.append({"id": i["InstanceId"], "state": i["State"]["Name"], "type": i.get("InstanceType"),
                           "public_ip": i.get("PublicIpAddress")})
    record["instances_found"] = states
    return jsonify(record)

@provision_bp.route("/provision/destroy", methods=["POST"])
def provision_destroy():
    body = request.get_json(force=True, silent=True) or {}
    region = body.get("region") or DEFAULT_REGION
    stack_id = body.get("stack_id")
    if not stack_id:
        return jsonify({"error": "Missing stack_id"}), 400

    cli = ec2(region)

    record = _STACKS.get(stack_id)
    network = (record or {}).get("network") or {}
    if not network:
        network = _discover_network_by_tag(cli, stack_id)

    if "created_vpc" not in network or network["created_vpc"] is None:
        created_vpc = False
        if network.get("vpc_id"):
            vpcs = cli.describe_vpcs(VpcIds=[network["vpc_id"]]).get("Vpcs", [])
            if vpcs:
                tags = {t["Key"]: t["Value"] for t in vpcs[0].get("Tags", [])}
                created_vpc = tags.get(STACK_TAG_KEY) == stack_id
        network["created_vpc"] = created_vpc

    _destroy_stack(cli, region, stack_id, network)
    if stack_id in _STACKS:
        del _STACKS[stack_id]

    return jsonify({"ok": True, "stack_id": stack_id, "deleted": network})
