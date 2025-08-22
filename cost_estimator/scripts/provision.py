# cost_estimator/scripts/provision.py
import os, time, uuid, traceback
from typing import Dict, Any, Optional, List
from flask import Blueprint, request, jsonify
import boto3
from botocore.config import Config

provision_bp = Blueprint("provision", __name__)

AWS_PROFILE_NAME = os.getenv("AWS_PROFILE") or os.getenv("CLOUD_MIGRATION_AWS_PROFILE")
DEFAULT_VOLUME_GB = int(os.getenv("DEFAULT_VOLUME_GB", "20"))

def _session(region: str):
    if AWS_PROFILE_NAME:
        return boto3.session.Session(profile_name=AWS_PROFILE_NAME, region_name=region)
    return boto3.session.Session(region_name=region)

def _clients(region: str):
    sess = _session(region)
    cfg = Config(retries={"max_attempts": 10, "mode": "standard"})
    return (
        sess.client("ec2", config=cfg),
        sess.client("ssm", config=cfg)
    )

def _supported_arch_for_type(ec2, instance_type: str) -> str:
    """Return 'arm64' if supported (Graviton), else 'x86_64'."""
    resp = ec2.describe_instance_types(InstanceTypes=[instance_type])
    it = (resp.get("InstanceTypes") or [{}])[0]
    archs = (it.get("ProcessorInfo") or {}).get("SupportedArchitectures") or []
    return "arm64" if "arm64" in archs else "x86_64"

def _latest_amazon_linux_2023(ssm, arch: str) -> str:
    name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-arm64" if arch == "arm64" \
           else "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
    p = ssm.get_parameter(Name=name)
    return p["Parameter"]["Value"]

def _get_or_create_default_vpc_stack(ec2) -> Dict[str, Any]:
    """Use default VPC if present; otherwise create a minimal VPC stack."""
    vpcs = ec2.describe_vpcs(Filters=[{"Name":"isDefault","Values":["true"]}]).get("Vpcs", [])
    if vpcs:
        vpc_id = vpcs[0]["VpcId"]
        # pick a default subnet in this VPC
        subs = ec2.describe_subnets(
            Filters=[{"Name":"vpc-id","Values":[vpc_id]}, {"Name":"default-for-az","Values":["true"]}]
        ).get("Subnets", [])
        subnet_id = subs[0]["SubnetId"] if subs else ec2.describe_subnets(
            Filters=[{"Name":"vpc-id","Values":[vpc_id]}]
        )["Subnets"][0]["SubnetId"]
        return {"vpc_id": vpc_id, "subnet_id": subnet_id, "created_vpc": False, "igw_id": None, "rtb_id": None}

    # create minimal VPC (only if truly no default VPC)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    vpc_id = vpc["VpcId"]
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})

    # pick first AZ
    az = ec2.describe_availability_zones()["AvailabilityZones"][0]["ZoneName"]
    subnet_id = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24", AvailabilityZone=az)["Subnet"]["SubnetId"]

    igw_id = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    rtb_id = ec2.create_route_table(VpcId=vpc_id)["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=rtb_id, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw_id)
    ec2.associate_route_table(RouteTableId=rtb_id, SubnetId=subnet_id)

    return {"vpc_id": vpc_id, "subnet_id": subnet_id, "created_vpc": True, "igw_id": igw_id, "rtb_id": rtb_id}

def _create_sg(ec2, vpc_id: str, stack_id: str) -> str:
    name = f"cmt-sg-{stack_id[:8]}"
    sg = ec2.create_security_group(GroupName=name, Description="Cloud Migration Tool SG", VpcId=vpc_id)
    sg_id = sg["GroupId"]
    # allow SSH/HTTP/HTTPS (IPv4 & IPv6)
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0"}],
             "Ipv6Ranges":[{"CidrIpv6":"::/0"}]},
            {"IpProtocol":"tcp","FromPort":80,"ToPort":80,"IpRanges":[{"CidrIp":"0.0.0.0/0"}],
             "Ipv6Ranges":[{"CidrIpv6":"::/0"}]},
            {"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0"}],
             "Ipv6Ranges":[{"CidrIpv6":"::/0"}]},
        ]
    )
    ec2.create_tags(Resources=[sg_id], Tags=[{"Key":"cmt:stack","Value":stack_id},{"Key":"Name","Value":name}])
    return sg_id

def _tag_resources(ec2, stack_id: str, tag_name: str, ids: List[str]):
    if ids:
        ec2.create_tags(Resources=ids, Tags=[{"Key":"cmt:stack","Value":stack_id},{"Key":"Name","Value":tag_name}])

@provision_bp.route("/provision/create", methods=["POST"])
def provision_create():
    try:
        body = request.get_json(force=True, silent=True) or {}
        region = body.get("region") or os.getenv("TARGET_REGION_CODE") or "us-east-1"
        instance_type = body.get("type") or "t3.micro"
        volume_gb = int(body.get("volume_gb") or DEFAULT_VOLUME_GB)
        tag_name = body.get("tag_name") or "cmt-demo"

        ec2, ssm = _clients(region)
        stack_id = f"cmt-{uuid.uuid4().hex[:8]}"

        # network (default VPC or minimal VPC)
        net = _get_or_create_default_vpc_stack(ec2)
        vpc_id, subnet_id = net["vpc_id"], net["subnet_id"]
        created_vpc = net["created_vpc"]

        # security group for this stack
        sg_id = _create_sg(ec2, vpc_id, stack_id)

        # image by arch
        arch = _supported_arch_for_type(ec2, instance_type)
        ami = _latest_amazon_linux_2023(ssm, arch)

        # run instance
        run = ec2.run_instances(
            ImageId=ami,
            InstanceType=instance_type,
            MinCount=1, MaxCount=1,
            SubnetId=subnet_id,
            SecurityGroupIds=[sg_id],
            BlockDeviceMappings=[
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {"VolumeSize": volume_gb, "VolumeType": "gp3", "DeleteOnTermination": True}
                }
            ],
            TagSpecifications=[{
                "ResourceType":"instance",
                "Tags":[{"Key":"cmt:stack","Value":stack_id},{"Key":"Name","Value":tag_name}]
            }]
        )
        inst = run["Instances"][0]
        instance_id = inst["InstanceId"]

        # Quick describe for IP/state (no long waiter)
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        i0 = desc["Reservations"][0]["Instances"][0]
        state = i0["State"]["Name"]
        public_ip = i0.get("PublicIpAddress")

        # Tag VPC if we created it (so destroy knows to remove it)
        to_tag = [id for id in [net.get("rtb_id"), net.get("igw_id"), vpc_id, subnet_id] if id]
        if created_vpc:
            _tag_resources(ec2, stack_id, tag_name, to_tag)

        return jsonify({
            "ok": True,
            "region": region,
            "stack_id": stack_id,
            "instance": {
                "id": instance_id,
                "state": state,
                "public_ip": public_ip,
                "type": instance_type,
                "image": ami,
                "arch": arch,
            },
            "network": {
                "vpc_id": vpc_id,
                "subnet_id": subnet_id,
                "security_group_id": sg_id,
                "created_vpc": created_vpc,
                "route_table_id": net.get("rtb_id"),
                "internet_gateway_id": net.get("igw_id"),
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

def _terminate_instances_by_stack(ec2, stack_id: str) -> List[str]:
    ids = []
    # find instances with our tag
    resp = ec2.describe_instances(
        Filters=[{"Name":"tag:cmt:stack","Values":[stack_id]}]
    )
    for r in resp.get("Reservations", []):
        for i in r.get("Instances", []):
            ids.append(i["InstanceId"])
    if ids:
        ec2.terminate_instances(InstanceIds=ids)
    return ids

def _wait_terminated(ec2, instance_ids: List[str], timeout_s: int = 60):
    if not instance_ids:
        return
    started = time.time()
    while time.time() - started < timeout_s:
        desc = ec2.describe_instances(InstanceIds=instance_ids)
        states = []
        for r in desc.get("Reservations", []):
            for i in r.get("Instances", []):
                states.append(i["State"]["Name"])
        if all(s in ("shutting-down","terminated") for s in states):
            return
        time.sleep(3)

def _delete_sg_by_stack(ec2, stack_id: str):
    sgs = ec2.describe_security_groups(
        Filters=[{"Name":"tag:cmt:stack","Values":[stack_id]}]
    ).get("SecurityGroups", [])
    for sg in sgs:
        try:
            ec2.delete_security_group(GroupId=sg["GroupId"])
        except Exception:
            pass

def _maybe_delete_vpc_stack(ec2, stack_id: str):
    # if we tagged a VPC with this stack_id, it's ours; tear down its parts
    vpcs = ec2.describe_vpcs(Filters=[{"Name":"tag:cmt:stack","Values":[stack_id]}]).get("Vpcs", [])
    for vpc in vpcs:
        vpc_id = vpc["VpcId"]
        # subnets
        subs = ec2.describe_subnets(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("Subnets", [])
        # route tables (skip the main default one if not tagged)
        rtbs = ec2.describe_route_tables(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("RouteTables", [])
        # igw
        igws = ec2.describe_internet_gateways(
            Filters=[{"Name":"attachment.vpc-id","Values":[vpc_id]}]).get("InternetGateways", [])

        # disassociate & delete non-main rtb
        for rtb in rtbs:
            # delete non-local routes
            for assoc in rtb.get("Associations", []):
                if assoc.get("Main"):
                    continue
                if assoc.get("RouteTableAssociationId"):
                    try:
                        ec2.disassociate_route_table(RouteTableAssociationId=assoc["RouteTableAssociationId"])
                    except Exception:
                        pass
            # delete routes (except local)
            for route in rtb.get("Routes", []):
                if route.get("GatewayId") and route["DestinationCidrBlock"] == "0.0.0.0/0":
                    try:
                        ec2.delete_route(RouteTableId=rtb["RouteTableId"], DestinationCidrBlock="0.0.0.0/0")
                    except Exception:
                        pass
            # try delete table if tagged to stack
            tags = {t["Key"]: t["Value"] for t in rtb.get("Tags", [])}
            if tags.get("cmt:stack") == stack_id:
                try:
                    ec2.delete_route_table(RouteTableId=rtb["RouteTableId"])
                except Exception:
                    pass

        # detach & delete igw
        for igw in igws:
            igw_id = igw["InternetGatewayId"]
            try:
                ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
            except Exception:
                pass
            try:
                ec2.delete_internet_gateway(InternetGatewayId=igw_id)
            except Exception:
                pass

        # delete subnets
        for s in subs:
            try:
                ec2.delete_subnet(SubnetId=s["SubnetId"])
            except Exception:
                pass

        # finally delete VPC
        try:
            ec2.delete_vpc(VpcId=vpc_id)
        except Exception:
            pass

@provision_bp.route("/provision/destroy", methods=["POST"])
def provision_destroy():
    try:
        body = request.get_json(force=True, silent=True) or {}
        region = body.get("region") or os.getenv("TARGET_REGION_CODE") or "us-east-1"
        stack_id = body.get("stack_id")
        if not stack_id:
            return jsonify({"ok": False, "error": "stack_id required"}), 400

        ec2, _ = _clients(region)
        ids = _terminate_instances_by_stack(ec2, stack_id)
        _wait_terminated(ec2, ids, timeout_s=60)
        _delete_sg_by_stack(ec2, stack_id)
        _maybe_delete_vpc_stack(ec2, stack_id)
        return jsonify({"ok": True, "terminated": ids})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

@provision_bp.route("/provision/status", methods=["GET"])
def provision_status():
    try:
        region = request.args.get("region") or os.getenv("TARGET_REGION_CODE") or "us-east-1"
        stack_id = request.args.get("stack_id")
        if not stack_id:
            return jsonify({"ok": False, "error": "stack_id required"}), 400

        ec2, _ = _clients(region)
        resp = ec2.describe_instances(Filters=[{"Name":"tag:cmt:stack","Values":[stack_id]}])
        items = []
        for r in resp.get("Reservations", []):
            for i in r.get("Instances", []):
                items.append({
                    "id": i["InstanceId"],
                    "state": i["State"]["Name"],
                    "type": i.get("InstanceType"),
                    "public_ip": i.get("PublicIpAddress"),
                })
        return jsonify({"ok": True, "stack_id": stack_id, "instances": items})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500
