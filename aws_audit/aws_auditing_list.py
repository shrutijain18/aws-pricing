#!/usr/bin/python3
# Provides attached/unattached instances for ELB for all regions
import boto3
import json
from datetime import datetime
import os
import pprint
from prettytable import PrettyTable
import argparse
import sys
from all_pricing import pricing_info

# Parser for command line
parser = argparse.ArgumentParser()
parser.add_argument(
    '--allpricing',
    '-a',
    help='pricing report for all regions',
)
parser.add_argument(
    '--region', '-r', help='pricing report for that region'
)
args = parser.parse_args()

# Creating Table
x = PrettyTable()
x.field_names = [
    'Region',
    'Service',
    'Instance_Type',
    'Count',
    'Price per hour',
    'Total Instances/Size',
    'Total cost per month',
]
x.align = 'l'


# To fix datetime object not serializable
class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()

        return json.JSONEncoder.default(self, o)

# To get the AWS resource report


class AWSAudit:
    def __init__(self):
        self.resources = {}
        self.dictionary = {}
        self.volume_ebs = {}
        self.snap_vol_id = []
        self.aws_region = []
        self.attached_vol_list = []
        self.unattached_vol_list = []
        self.state = 'running'
        self.per_month_hours = 730.5
        self.con = self.connect_service('ec2')
        self.sts_client = self.connect_service('sts')
        self.aws_regions = self.region(self.aws_region)

        self.initialize_resource_dict(self.aws_regions)
        self.get_ec2_resources(self.aws_regions)
        self.get_classic_elb_resources(self.aws_regions)
        self.get_network_elb_resources(self.aws_regions)
        self.get_ebs_resources(self.aws_regions)
        self.get_price(
            self.aws_regions,
            self.volume_ebs,
        )

    def region(self, aws_region):
        if args.region:
            aws_region = [args.region]
        else:
            aws_region = [
                d['RegionName']for d in self.con.describe_regions()['Regions']
            ]
        return aws_region

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
                'ELB': {},
                'ELBV2': {},
                'EC2': {},
                'EBS': {'orphaned_snapshots': []},
            }
        self.dictionary = resources_dict

    # Get EC2 resources
    def get_ec2_resources(self, regions):
        for region_name in regions:
            conn = self.connect_service_region(
                'ec2',
                region_name=region_name
            )
            instance_list = conn.describe_instances()
            
            for r in instance_list['Reservations']:
                for i in r['Instances']:
                    instance_id = i['InstanceId']
                    if 'KeyName' in i:
                        key_name = i['KeyName']
                    else:
                        key_name = ''

                    self.dictionary[region_name]['EC2'][instance_id] = {
                        'key_name': key_name,
                        'launch_time': i['LaunchTime'],
                        'instance_state': i['State']['Name'],
                        'instance_type': i['InstanceType']
                    }

    # Get Classic ELB
    def get_classic_elb_resources(self, regions):
        for region_name in regions:
            conn = self.connect_service_region(
                'elb',
                region_name=region_name
            )
            lb = conn.describe_load_balancers()
            for l in lb['LoadBalancerDescriptions']:
                self.dictionary[region_name]['ELB'][l['LoadBalancerName']] = {'instanceId': []}

                if l['Instances']:
                    self.dictionary[region_name]['ELB'][l['LoadBalancerName']]['instanceId'] = [id for id in l['Instances']]
                else:
                    self.dictionary[region_name]['ELB'][l['LoadBalancerName']]['instanceId'] = []

    # Get Network ELB
    def get_network_elb_resources(self, regions):
        for region_name in regions:
            conn = self.connect_service_region(
                'elbv2',
                region_name=region_name
            )
            lb = conn.describe_load_balancers()
            network_elb = len(lb['LoadBalancers'])
            self.dictionary[region_name]['ELBV2'] = {
                'Length': network_elb
            }

    # Get Volumes and Snapshots
    def get_ebs_resources(self, regions):
        sts_response = self.sts_client.get_caller_identity()
        user_account = sts_response['Account']

        for region_name in regions: 
            conn = self.connect_service_region(
                'ec2',
                region_name=region_name
            )

            volumes = conn.describe_volumes()
            snapshots = conn.describe_snapshots(
                Filters=[
                    {
                        'Name': 'owner-id',
                        'Values': [str(user_account)],
                    }
                ]
            )

            for vol in volumes['Volumes']:
                vol_id = vol['VolumeId']
                self.dictionary[region_name]['EBS'][vol_id] = {
                    'state': vol['State'],
                    'snapshots': [],
                    'size': vol['Size'],
                    'volumeType': vol['VolumeType'],
                }

            # Get all snapshots and assign them to their volume
            for snapshot in snapshots['Snapshots']:
                snap = snapshot['VolumeId']
                if (snap in self.dictionary[region_name]['EBS']):
                    self.dictionary[region_name]['EBS'][snap]['snapshots'].append(snapshot['SnapshotId'])
                else:
                    self.dictionary[region_name]['EBS']['orphaned_snapshots'].append(snapshot['SnapshotId'])            
    
    # List EC2 instances                   
    def list_instances(self, state, region):
        instances_per_state = []
        for i in self.dictionary[region]['EC2']:
            if self.dictionary[region]['EC2'][i]['instance_state'] == state and i not in instances_per_state:
                instances_per_state.append(i)
               
        return(instances_per_state)
    
    # Count EC2 Instances   
    def count_instance_types(self, instances_per_state, region):
        count_instance_type = {}
        for instance_id in instances_per_state:
            if instance_id in self.dictionary[region]['EC2']:
                instance_type = self.dictionary[region]['EC2'][instance_id]['instance_type']
                if instance_type not in count_instance_type:
                    count_instance_type[instance_type] = {'count': 1}
                else:
                    count_instance_type[instance_type]['count'] += 1
        return(count_instance_type)
    
    # Count Classic ELB's 
    def count_classic_elb(self, region):
        return (len(self.dictionary[region]['ELB']))

    # Count Network ELB's          
    def count_network_elb(self, region):
        return (self.dictionary[region]['ELBV2']['Length'])

    # Count orphaned and attached snapshots      
    def count_snapshots(self, count_type, region):
        attached_snapshot_count = 0
        for vol_id in self.dictionary[region]['EBS']:
            if vol_id == 'orphaned_snapshots':
                continue
            if vol_id in self.dictionary[region]['EBS']:
                if len(self.dictionary[region]['EBS'][vol_id]['snapshots']) > 0:
                    self.snap_vol_id.append(vol_id)
                    attached_snapshot_count += 1   
        
        if count_type == 'attached':
            return attached_snapshot_count
        else:
            orphaned_snapshot_count = len(self.dictionary[region]['EBS']['orphaned_snapshots'])
            return orphaned_snapshot_count
   
    # Count attached and orphaned volumes
    def list_volumes(self, regions):
        conn = self.connect_service_region(
                'ec2',
                region_name=regions
            )
        volumes = conn.describe_volumes()
        for vol in volumes['Volumes']:
            if len(vol['Attachments']) > 0:
                if not vol['VolumeId'] in self.attached_vol_list:
                    self.attached_vol_list.append(vol['VolumeId'])
            else:
                if not vol['VolumeId'] in self.unattached_vol_list:
                    self.unattached_vol_list.append(vol['VolumeId'])
    
    # Count volume types and repsective volume size
    def count_volume_types(self, vol_list, vol_list_type, region):
        # Dictionary to store the count and size
        devices_dict = {}

        if vol_list_type == 'attached':
            vol_list = self.attached_vol_list
        else:
            vol_list = self.unattached_vol_list
        
        for vol_id in vol_list:
            if vol_id in self.dictionary[region]['EBS']:
                v_type = self.dictionary[region]['EBS'][vol_id]['volumeType']
                if v_type in devices_dict:
                    devices_dict[v_type]['count'] += 1
                    devices_dict[v_type]['size'] += self.dictionary[region]['EBS'][vol_id]['size']

                else:
                    devices_dict[v_type] = {
                        'count': 1,
                        'size': 1,
                    }
        
        self.volume_ebs[region] = devices_dict
        return self.volume_ebs[region]
   
    # Get monthly estimated cost for AWS resources
    def get_price(
        self,
        regions,
        volume
    ):
        # with open('epl1.json', 'r') as fp:
        #     pricing_json = json.load(fp)
        # with open('snapshots_price.json', 'r') as fp:
        #     snapshot_pricing = json.load(fp)
        
        p_info = pricing_info()
        elbv2 = p_info.price_list_ELBV2()
        elb = p_info.price_list_ELB()
        vol_pricing = p_info.price_list_EBS()
        pricing_json = p_info.price_list_EC2()
        snapshot_pricing = p_info.price_list_snapshots()

        # Pricing
        for region in regions:
            x.add_row(
                [
                    region,
                    '',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            total_instances = 0
            total_size = 0
            price_per_month = 0
            price = 0
            total_cost = 0.00
            unattached_volume_cost = 0.00
            attached_volume_cost = 0.00
            unattached_length = 0
            attached_length = 0

        # EC2 pricing
            x.add_row(
                [
                    '',
                    'EC2 Instances',
                    '',
                    '',
                    '',
                    '',
                    '',
                ]
            )
            count_of_instances = self.count_instance_types(self.list_instances(self.state, region), region)
            for i_type in count_of_instances:
                if i_type in (instance_type for instance_type in pricing_json[region]['EC2']):
                    price = round(float(pricing_json[region]['EC2'][i_type]['OnDemand']['USD']),3)
                    total_cost = round(float(total_cost + (price * count_of_instances[i_type]['count'])), 3)
                    total_instances += count_of_instances[i_type]['count']

                x.add_row(
                    [
                        '',
                        '',
                        i_type,
                        count_of_instances[i_type]['count'],
                        price,
                        '',
                        '',
                    ]
                )

            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    '',
                    total_instances,
                    round((total_cost * self.per_month_hours),3),
                ]
            )
            
        # Classic ELB pricing
            x.add_row(
                [
                    '',
                    'ELB Classic',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            
            classic_elb_instances = self. count_classic_elb(region)
            price = float(elb[region]['ELB']['OnDemand']['USD'])
            total_cost = round(float(price * classic_elb_instances * self.per_month_hours),3)

            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    price,
                    classic_elb_instances,
                    total_cost,
                ]
            )

        # Network ELB pricing
            x.add_row(
                [
                    '',
                    'ELB Network',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            network_elb_instances = self.count_network_elb(region)
            price = float(elbv2[region]['ELBV2']['OnDemand']['USD'])
            total_cost = round(
                float(price * network_elb_instances * self.per_month_hours),
                3,
            )
            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    price,
                    network_elb_instances,
                    total_cost,
                ]
            )

        # Volume pricing
            x.add_row(
                [
                    '',
                    'Volume',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            x.add_row(
                [
                    '',
                    '',
                    'Attached Volume',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            attached_vol_dict = self.count_volume_types(
                self.list_volumes(region),
                'attached',
                region
                )
            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            for volume_type in attached_vol_dict:
                if volume_type in (v_type for v_type in vol_pricing[region]['EBS']):
                    attached_length += attached_vol_dict[volume_type]['count']
                    price = float(vol_pricing[region]['EBS'][volume_type]['OnDemand']['USD'])
                    attached_volume_cost = round(
                        float(float(attached_vol_dict[volume_type]['size'])
                        * price 
                        + attached_volume_cost), 3)
                    x.add_row(
                        [
                            '',
                            '',
                            volume_type,
                            attached_vol_dict[volume_type]['count'],
                            price,
                            attached_vol_dict[volume_type]['size'],
                            '',
                        ]
                    )
            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    'Total Attached Volumes',
                    attached_length,
                    attached_volume_cost,
                ]
            )
            
            x.add_row(
                [
                    '',
                    '',
                    'Orphaned Volume',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            unattached_vol_dict = self.count_volume_types(
                self.list_volumes(region),
                'unattached',
                region
                )
            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            for volume_type in unattached_vol_dict:
                if volume_type in (v_type for v_type in vol_pricing[region]['EBS']):
                    unattached_length += unattached_vol_dict[volume_type]['count']
                    price = float(vol_pricing[region]['EBS'][volume_type]['OnDemand']['USD'])
                    unattached_volume_cost = round(
                        float(float(unattached_vol_dict[volume_type]['size'])
                        * price 
                        + unattached_volume_cost), 3)
                    x.add_row(
                        [
                            '',
                            '',
                            volume_type,
                            unattached_vol_dict[volume_type]['count'],
                            price,
                            unattached_vol_dict[volume_type]['size'],
                            '',
                        ]
                    )
            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    'Total Orphaned Volumes',
                    unattached_length,
                    unattached_volume_cost,
                ]
            )
            
            # Snapshot pricing
            x.add_row(
                [
                    '',
                    'Snapshots',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            x.add_row(
                [
                    '',
                    '',
                    '',
                    '',
                    '',
                    '',
                    ''
                ]
            )
            attached_snap = self.count_snapshots('attached', region) 
            price = float(snapshot_pricing[region]['Snapshots']['OnDemand']['USD'])
            for volume_id in self.snap_vol_id:
                if volume_id in (vol_id for vol_id in self.dictionary[region]['EBS']):
                    size = self.dictionary[region]['EBS'][volume_id]['size']
                    total_size += size
                price_per_month = round(
                    float(price 
                    * float(total_size)), 3
                )
            x.add_row(
                [
                    '',
                    '',
                    'snapshots',
                    attached_snap,
                    price,
                    total_size,
                    price_per_month,
                ]
            )
            orphaned_snap = self.count_snapshots('unattached', region) 
            x.add_row(
                [
                    '',
                    '',
                    'orphaned snapshots',
                    orphaned_snap,
                    price,
                    '',
                    round(
                        float(price
                            * orphaned_snap), 3)
                ]
            )

        print(x)


aws_audit = AWSAudit()
