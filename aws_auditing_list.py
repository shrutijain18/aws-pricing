#!/usr/bin/python3
# Provides attached/unattached instances for ELB for all regions
import boto3
import json
from datetime import datetime
import os
import pickle
import pprint
from prettytable import PrettyTable
import argparse
import sys

# Parser for command line
parser = argparse.ArgumentParser()
parser.add_argument(
    "--allpricing",
    "-a",
    help="pricing report for all regions",
)
parser.add_argument(
    "--region", "-r", help="pricing report for that region"
)
args = parser.parse_args()

# Creating Table
x = PrettyTable()
x.field_names = [
    "Region",
    "Service",
    "Instance_Type",
    "Count",
    "Price per hour",
    "Total Instances/Size",
    "Total cost per month",
]
x.align = "l"


# To fix datetime object not serializable
class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()

        return json.JSONEncoder.default(self, o)


class AWSAudit:
    def __init__(self):
        self.resources = {}
        self.dictionary = {}
        self.ec2_counts = {}
        self.classic_elb = {}
        self.network_elb = {}
        self.volume_ebs = {}
        self.snapshot_ebs = {}
        self.snap_vol_id = {}

        self.con = self.connect_service("ec2")
        self.sts_client = self.connect_service("sts")

        if args.region:
            self.aws_regions = [args.region]
        else:
            self.aws_regions = [
                d["RegionName"]
                for d in self.con.describe_regions()[
                    "Regions"
                ]
            ]

        self.initialize_resource_dict(self.aws_regions)
        self.get_ec2_resources(self.aws_regions)
        self.get_classic_elb_resources(self.aws_regions)
        self.get_network_elb_resources(self.aws_regions)
        self.get_ebs_resources(self.aws_regions)
        self.get_price(
            self.ec2_counts,
            self.classic_elb,
            self.network_elb,
            self.volume_ebs,
            self.snapshot_ebs,
        )

    def connect_service_region(
        self, service, region_name=None
    ):
        return boto3.client(service, region_name)

    def connect_service(self, service):
        return boto3.client(service)

    def initialize_resource_dict(self, regions):
        resources_dict = {}
        for region_name in regions:
            resources_dict[region_name] = {
                "ELB": {},
                "ELBV2": {},
                "EC2": {},
                "EBS": {"orphaned_snapshots": []},
            }
        self.dictionary = resources_dict

    def get_ec2_resources(self, regions):
        for region_name in regions:
            self.ec2_counts[region_name] = {}
            count_list = {}
            conn = self.connect_service_region(
                "ec2", region_name=region_name
            )
            instance_list = conn.describe_instances()

            for r in instance_list["Reservations"]:
                for i in r["Instances"]:

                    if "KeyName" in i:
                        key_name = i["KeyName"]
                    else:
                        key_name = ""

                    self.dictionary[region_name]["EC2"][
                        id
                    ] = {
                        "type": i["InstanceType"],
                        "key_name": key_name,
                        "launch_time": i["LaunchTime"],
                        "state": i["State"]["Name"],
                    }
                    instance_type = i["InstanceType"]
                    if i["State"]["Name"] == "running":
                        if instance_type in count_list:
                            count_list[instance_type][
                                "count"
                            ] += 1

                        else:
                            count_list[instance_type] = {
                                "count": 0
                            }
            self.ec2_counts[region_name] = count_list

    def get_classic_elb_resources(self, regions):
        with open("elb_pricing.json", "r") as elb:
            elb_pricing = json.load(elb)

        for region_name in regions:
            self.classic_elb[region_name] = {}
            conn = self.connect_service_region(
                "elb", region_name=region_name
            )
            lb = conn.describe_load_balancers()
            total_instances = len(
                lb["LoadBalancerDescriptions"]
            )

            for l in lb["LoadBalancerDescriptions"]:
                self.dictionary[region_name]["ELB"][
                    l["LoadBalancerName"]
                ] = {"instanceId": []}

                if l["Instances"]:
                    self.dictionary[region_name]["ELB"][
                        l["LoadBalancerName"]
                    ]["instanceId"] = [
                        id for id in l["Instances"]
                    ]
                else:
                    self.dictionary[region_name]["ELB"][
                        l["LoadBalancerName"]
                    ]["instanceId"] = []

            for term in elb_pricing[region_name]["ELB"][
                "OnDemand"
            ]:
                elb_price = float(
                    elb_pricing[region_name]["ELB"][
                        "OnDemand"
                    ]["USD"]
                )
                total_elb_cost = round(
                    float(
                        elb_price * total_instances * 730.5
                    ),
                    3,
                )

            self.classic_elb[region_name] = {
                "total_instances": total_instances,
                "price": elb_price,
                "total_elb_cost": total_elb_cost,
            }

    def get_network_elb_resources(self, regions):
        with open("elbv2_pricing.json", "r") as elb2:
            elbv2_pricing = json.load(elb2)

        for region_name in regions:
            TOTAL_ELBV2_COST = 0
            self.network_elb[region_name] = {}

            conn = self.connect_service_region(
                "elbv2", region_name=region_name
            )
            lb = conn.describe_load_balancers()
            network_elb = len(lb["LoadBalancers"])
            self.dictionary[region_name]["ELBV2"] = {
                "Length": network_elb
            }

            for elbv2_price in elbv2_pricing[region_name][
                "ELB"
            ]["OnDemand"]:
                elbv2_cost = float(
                    elbv2_pricing[region_name]["ELB"][
                        "OnDemand"
                    ]["USD"]
                )
                TOTAL_ELBV2_COST = round(
                    float(elbv2_cost * network_elb * 730.5),
                    3,
                )
                self.network_elb[region_name] = {
                    "Elbv2_Cost": TOTAL_ELBV2_COST,
                    "Total_length": network_elb,
                    "Cost": elbv2_cost,
                }

    def get_ebs_resources(self, regions):
        with open("ebs_pricing_list.json", "r") as ebs:
            vol_pricing = json.load(ebs)
        sts_response = self.sts_client.get_caller_identity()
        user_account = sts_response["Account"]

        for region_name in regions:
            snap_vol = []
            self.snap_vol_id[region_name] = {}
            self.volume_ebs[region_name] = {
                "attached": {},
                "unattached": {},
            }
            attached_list = {}
            unattached_list = {}
            self.snapshot_ebs[region_name] = {}
            snap_vol = []
            attached_vol_list = []
            unattached_vol_list = []
            conn = self.connect_service_region(
                "ec2", region_name=region_name
            )

            volumes = conn.describe_volumes()
            snapshots = conn.describe_snapshots(
                Filters=[
                    {
                        "Name": "owner-id",
                        "Values": [str(user_account)],
                    }
                ]
            )

            for vol in volumes["Volumes"]:
                if len(vol["Attachments"]):
                    if (
                        not vol["VolumeId"]
                        in attached_vol_list
                    ):
                        attached_vol_list.append(
                            vol["VolumeId"]
                        )
                else:
                    if (
                        not vol["VolumeId"]
                        in unattached_vol_list
                    ):
                        unattached_vol_list.append(
                            vol["VolumeId"]
                        )

                vol_id = vol["VolumeId"]
                self.dictionary[region_name]["EBS"][
                    vol_id
                ] = {
                    "state": vol["State"],
                    "snapshots": [],
                    "size": vol["Size"],
                    "volumeType": vol["VolumeType"],
                }

                v_type = vol["VolumeType"]
                for vol_type in vol_pricing[region_name][
                    "EBS"
                ]:
                    if (
                        self.dictionary[region_name]["EBS"][
                            vol_id
                        ]["volumeType"]
                        in vol_type
                    ):
                        if vol_id in attached_vol_list:
                            if v_type in attached_list:
                                attached_list[v_type][
                                    "count"
                                ] += 1
                                attached_list[v_type][
                                    "size"
                                ] += self.dictionary[
                                    region_name
                                ][
                                    "EBS"
                                ][
                                    vol_id
                                ][
                                    "size"
                                ]
                                attached_list[v_type][
                                    "price"
                                ] = float(
                                    vol_pricing[
                                        region_name
                                    ]["EBS"][v_type][
                                        "OnDemand"
                                    ][
                                        "USD"
                                    ]
                                )

                            else:
                                attached_list[v_type] = {
                                    "count": 0,
                                    "size": 0,
                                }

                        if vol_id in unattached_vol_list:
                            if v_type in unattached_list:
                                unattached_list[v_type][
                                    "count"
                                ] += 1
                                unattached_list[v_type][
                                    "size"
                                ] += self.dictionary[
                                    region_name
                                ][
                                    "EBS"
                                ][
                                    vol_id
                                ][
                                    "size"
                                ]
                                unattached_list[v_type][
                                    "price"
                                ] = float(
                                    vol_pricing[
                                        region_name
                                    ]["EBS"][v_type][
                                        "OnDemand"
                                    ][
                                        "USD"
                                    ]
                                )

                            else:
                                unattached_list[v_type] = {
                                    "count": 0,
                                    "size": 0,
                                }

                self.volume_ebs[region_name][
                    "attached"
                ] = attached_list
                self.volume_ebs[region_name][
                    "unattached"
                ] = unattached_list

            # Get all snapshots and assign them to their volume
            ORPHANED_SNAPSHOT_COUNT = 0
            SNAPSHOT_COUNT = 0
            for snapshot in snapshots["Snapshots"]:
                snap = snapshot["VolumeId"]
                if (
                    snap
                    in self.dictionary[region_name]["EBS"]
                ):
                    self.dictionary[region_name]["EBS"][
                        snap
                    ]["snapshots"].append(
                        snapshot["SnapshotId"]
                    )
                    if not snap in snap_vol:
                        snap_vol.append(snap)
                        SNAPSHOT_COUNT += 1
                else:
                    self.dictionary[region_name]["EBS"][
                        "orphaned_snapshots"
                    ].append(snapshot["SnapshotId"])
                    ORPHANED_SNAPSHOT_COUNT += 1

            self.snap_vol_id[region_name] = snap_vol

            self.snapshot_ebs[region_name] = {
                "sc": SNAPSHOT_COUNT,
                "osc": ORPHANED_SNAPSHOT_COUNT,
            }

    def get_price(
        self,
        EC2_counts,
        classic_elb,
        network_elb,
        volume,
        snapshot,
    ):
        with open("epl1.json", "r") as fp:
            pricing_json = json.load(fp)
        with open("snapshots_price.json", "r") as fp:
            snapshot_pricing = json.load(fp)

        # Pricing
        for region in EC2_counts:
            x.add_row([region, "", "", "", "", "", ""])
            TOTAL_COST_OF_INSTANCES = 0
            TOTAL_SIZE = 0
            PRICE_PER_MONTH = 0
            SNAPSHOT_COUNT_LENGTH = 0
            ORPHANED_SNAPSHOT_COUNT_LENGTH = 0
            PRICE = 0
            TOTAL_COST = 0.00
            UNATTACHED_VOLUME_COST = 0.00
            ATTACHED_VOLUME_COST = 0.00
            UNATTACHED_LENGTH = 0
            ATTACHED_LENGTH = 0

            # EC2 pricing
            x.add_row(
                [
                    "",
                    "EC2 Running Instances",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
            for i_types in EC2_counts[region]:
                if i_types in (
                    instance_type
                    for instance_type in pricing_json[
                        region
                    ]["EC2"]
                ):
                    count_of_instances = round(
                        float(
                            EC2_counts[region][i_types][
                                "count"
                            ]
                        ),
                        3,
                    )
                    PRICE = round(
                        float(
                            pricing_json[region]["EC2"][
                                i_types
                            ]["OnDemand"]["USD"]
                        ),
                        3,
                    )
                    TOTAL_COST_OF_INSTANCES += EC2_counts[
                        region
                    ][i_types]["count"]
                    TOTAL_COST = round(
                        float(
                            TOTAL_COST
                            + (PRICE * count_of_instances)
                        ),
                        3,
                    )

                    x.add_row(
                        [
                            "",
                            "",
                            i_types,
                            EC2_counts[region][i_types][
                                "count"
                            ],
                            PRICE,
                            "",
                            "",
                        ]
                    )

            x.add_row(
                [
                    "",
                    "",
                    "",
                    "",
                    "",
                    TOTAL_COST_OF_INSTANCES,
                    TOTAL_COST * 730.5,
                ]
            )

            # Classic ELB pricing
            x.add_row(
                ["", "ELB Classic", "", "", "", "", ""]
            )
            if (
                region in classic_elb
                and "total_elb_cost" in classic_elb[region]
                and "price" in classic_elb[region]
                and "total_instances" in classic_elb[region]
            ):
                x.add_row(
                    [
                        "",
                        "",
                        "",
                        "",
                        classic_elb[region]["price"],
                        classic_elb[region][
                            "total_instances"
                        ],
                        classic_elb[region][
                            "total_elb_cost"
                        ],
                    ]
                )

            # Network ELB pricing
            x.add_row(
                ["", "ELB Network", "", "", "", "", ""]
            )
            if region in network_elb:
                x.add_row(
                    [
                        "",
                        "",
                        "",
                        "",
                        network_elb[region]["Cost"],
                        network_elb[region]["Total_length"],
                        network_elb[region]["Elbv2_Cost"],
                    ]
                )

            # Volume pricing
            x.add_row(["", "Volume", "", "", "", "", ""])
            x.add_row(
                ["", "", "Attached Volume", "", "", "", ""]
            )
            x.add_row(["", "", "", "", "", "", ""])
            for status in volume[region]:
                for vtype in volume[region][status]:
                    if status == "attached":
                        ATTACHED_LENGTH += volume[region][
                            status
                        ][vtype]["count"]
                        ATTACHED_VOLUME_COST = round(
                            float(
                                (
                                    float(
                                        volume[region][
                                            status
                                        ][vtype]["size"]
                                    )
                                    * volume[region][
                                        status
                                    ][vtype]["price"]
                                )
                                + ATTACHED_VOLUME_COST
                            ),
                            3,
                        )
                        x.add_row(
                            [
                                "",
                                "",
                                vtype,
                                volume[region][status][
                                    vtype
                                ]["count"],
                                volume[region][status][
                                    vtype
                                ]["price"],
                                volume[region][status][
                                    vtype
                                ]["size"],
                                "",
                            ]
                        )
            x.add_row(
                [
                    "",
                    "",
                    "",
                    "",
                    "Total Attached Volumes",
                    ATTACHED_LENGTH,
                    ATTACHED_VOLUME_COST,
                ]
            )
            x.add_row(["", "", "", "", "", "", ""])
            x.add_row(
                ["", "", "Orphaned Volume", "", "", "", ""]
            )
            x.add_row(["", "", "", "", "", "", ""])
            for status in volume[region]:
                for vtype in volume[region][status]:
                    if status == "unattached":
                        UNATTACHED_LENGTH += volume[region][
                            status
                        ][vtype]["count"]
                        UNATTACHED_VOLUME_COST = round(
                            float(
                                (
                                    float(
                                        volume[region][
                                            status
                                        ][vtype]["size"]
                                    )
                                    * volume[region][
                                        status
                                    ][vtype]["price"]
                                )
                                + UNATTACHED_VOLUME_COST
                            ),
                            3,
                        )
                        x.add_row(
                            [
                                "",
                                "",
                                vtype,
                                volume[region][status][
                                    vtype
                                ]["count"],
                                volume[region][status][
                                    vtype
                                ]["price"],
                                volume[region][status][
                                    vtype
                                ]["size"],
                                "",
                            ]
                        )
            x.add_row(
                [
                    "",
                    "",
                    "",
                    "",
                    "Total Orphaned Volumes",
                    UNATTACHED_LENGTH,
                    UNATTACHED_VOLUME_COST,
                ]
            )

            # Snapshots pricing
            x.add_row(["", "Snapshots", "", "", "", "", ""])
            x.add_row(["", "", "", "", "", "", ""])
            if region in snapshot:
                SNAPSHOT_COUNT_LENGTH = snapshot[region][
                    "sc"
                ]
                ORPHANED_SNAPSHOT_COUNT_LENGTH = snapshot[
                    region
                ]["osc"]
            if region in (reg for reg in snapshot_pricing):
                PRICE = float(
                    snapshot_pricing[region]["Snapshot"][
                        "OnDemand"
                    ]["USD"]
                )
            for volume_id in self.snap_vol_id[region]:
                if volume_id in (
                    vol_id
                    for vol_id in self.dictionary[region][
                        "EBS"
                    ]
                ):
                    size = self.dictionary[region]["EBS"][
                        volume_id
                    ]["size"]
                    TOTAL_SIZE += size
                PRICE_PER_MONTH = round(
                    float(PRICE * float(TOTAL_SIZE)), 3
                )
            x.add_row(
                [
                    "",
                    "",
                    "snapshots",
                    SNAPSHOT_COUNT_LENGTH,
                    PRICE,
                    TOTAL_SIZE,
                    PRICE_PER_MONTH,
                ]
            )
            x.add_row(
                [
                    "",
                    "",
                    "orphaned snapshots",
                    ORPHANED_SNAPSHOT_COUNT_LENGTH,
                    PRICE,
                    "",
                    round(
                        float(
                            PRICE
                            * ORPHANED_SNAPSHOT_COUNT_LENGTH
                        ),
                        3,
                    ),
                ]
            )

        print(x)


aws_audit = AWSAudit()
