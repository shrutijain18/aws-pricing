import boto3
import json
import pprint 
import re
import sys

from constants import (
    region_short_names,
    aws_region
)

from connection import (
    region,
    session,
    ec2,
    pricing_client
)

class pricing_info:
    def __init__(self):
        self.pricing = {}
        self.price_item = []
        self.volume_types = {
            'gp2': 'General Purpose',
            'io1': 'Provisioned IOPS',
            'sc1': 'Cold HDD',
            'st1': 'Throughput Optimized HDD',
            'standard': 'Magnetic'
            }
        self.pricing_dict()
        self.paginator_connection()
        # self.price_list_EBS()
        # self.price_list_ELBV2()
        # self.price_list_ELB()
        # self.price_list_EC2()
                
    def pricing_dict(self):
        for region in aws_region:
            self.pricing[region] = {
                'EC2': {},
                'Snapshots': {},
                'ELB': {},
                'ELBV2': {},
                'EBS': {}
            }
    
    def paginator_connection(self):
        return pricing_client.get_paginator('get_products')

    def onDemand_variables(self, terms, variable_type):
        self.product_sku = list(terms[variable_type].keys())
        self.pd = terms[variable_type][self.product_sku[0]]['priceDimensions']
        self.product_price_sku = list(self.pd.keys())
        self.price = self.pd[self.product_price_sku[0]]['pricePerUnit']['USD']
        self.description = self.pd[self.product_price_sku[0]]['description']

    def response_pages(self, price_list_type):
        paginator = self.paginator_connection()
        if price_list_type == 'EC2':
            resp_pages = paginator.paginate(ServiceCode='AmazonEC2',
                                            Filters=[
                                                {'Type':'TERM_MATCH', 
                                                'Field':'preInstalledSw', 
                                                'Value':'NA'},
                                                {'Type':'TERM_MATCH', 
                                                'Field':'operatingSystem', 
                                                'Value':'Linux'},
                                                {'Type':'TERM_MATCH', 
                                                'Field':'tenancy', 
                                                'Value':'Shared'},
                                                {'Type':'TERM_MATCH', 
                                                'Field':'licenseModel', 
                                                'Value':'No License required'},
                                                {'Type':'TERM_MATCH', 
                                                'Field':'capacitystatus', 
                                                'Value':'Used'}
                                            ])
        
        if price_list_type == 'ELB':
            resp_pages = paginator.paginate(ServiceCode='AmazonEC2',
                                        Filters=[
                                            {'Type':'TERM_MATCH', 
                                            'Field':'productFamily', 
                                            'Value':'Load Balancer'},
                                            ])

        if price_list_type == 'ELBV2':
            resp_pages = paginator.paginate(ServiceCode='AmazonEC2',
                                        Filters=[
                                            {'Type':'TERM_MATCH', 
                                            'Field':'productFamily', 
                                            'Value':'Load Balancer-Network'},
                                            ])
        if price_list_type == 'Snapshots':
            resp_pages = paginator.paginate(ServiceCode="AmazonEC2",
                                        Filters=[
                                            {'Type': 'TERM_MATCH', 
                                            'Field': 'productFamily', 
                                            'Value': 'Storage Snapshot'}
                                            ]
                                            )
        if price_list_type == 'EBS':
            resp_pages = paginator.paginate(ServiceCode='AmazonEC2',
                                        Filters=[
                                            {'Type':'TERM_MATCH', 
                                            'Field':'productFamily', 
                                            'Value':'Storage'},
                                            ])
        
        self.terms_list(resp_pages)
    
    def terms_list(self, resp_pages):
        for page in resp_pages:
            for item in page['PriceList']:
                self.price_item.append(json.loads(item))

    def price_list_ELBV2(self):
        self.response_pages('ELBV2')
        for item in self.price_item:
            terms = item['terms']
            if 'OnDemand' in terms:
                region = region_short_names[item['product']['attributes']['location']]
                self.onDemand_variables(terms, 'OnDemand')

                if not 'OnDemand' in self.pricing[region]['ELBV2']:
                    self.pricing[region]['ELBV2']['OnDemand'] = {}

                self.pricing[region]['ELBV2']['OnDemand'] = {
                                'Description': self.description,
                                'UsageType': item['product']['attributes']['usagetype'],
                                'Location': item['product']['attributes']['location'],
                                'USD': self.price
                                }
        return self.pricing

    def price_list_EBS(self):
        self.response_pages('EBS')
        for item in self.price_item:
            terms = item['terms']
            if 'volumeType' in item['product']['attributes']:
                volume_type = list(self.volume_types.keys())[list(self.volume_types.values()).index(item['product']['attributes']['volumeType'])]

                if 'OnDemand' in terms:
                    region = region_short_names[item['product']['attributes']['location']]
                    self.onDemand_variables(terms, 'OnDemand')

                    if not volume_type in self.pricing[region]['EBS']:
                        self.pricing[region]['EBS'][volume_type] = {}
                    if not 'OnDemand' in self.pricing[region]['EBS'][volume_type]:
                        self.pricing[region]['EBS'][volume_type]['OnDemand'] = {}

                    self.pricing[region]['EBS'][volume_type]['OnDemand'] = {
                                    'Description': self.description,
                                    'UsageType': item['product']['attributes']['usagetype'],
                                    'Location': item['product']['attributes']['location'],
                                    'Max Volume Size': item['product']['attributes']['maxVolumeSize'],
                                    'USD': self.price
                                    }
        return self.pricing
    
    def price_list_snapshots(self):
        self.response_pages('Snapshots')
        for item in self.price_item:
            terms = item['terms']
            if 'OnDemand' in terms:
                region = region_short_names[item['product']['attributes']['location']]
                self.onDemand_variables(terms, 'OnDemand')
                
                if not 'OnDemand' in self.pricing[region]['Snapshots']:
                    self.pricing[region]['Snapshots']['OnDemand'] = {}

                self.pricing[region]['Snapshots']['OnDemand'] = {
                                'Description': self.description,
                                'UsageType': item['product']['attributes']['usagetype'],
                                'Location': item['product']['attributes']['location'],
                                'USD': self.price
                                }
        return self.pricing

    def price_list_ELB(self):
        self.response_pages('ELB')
        for item in self.price_item:
            terms = item['terms']
            if 'OnDemand' in terms:
                region = region_short_names[item['product']['attributes']['location']]
                self.onDemand_variables(terms, 'OnDemand')

                if not 'OnDemand' in self.pricing[region]['ELB']:
                    self.pricing[region]['ELB']['OnDemand'] = {}

                self.pricing[region]['ELB']['OnDemand'] = {
                                'Description': self.description,
                                'UsageType': item['product']['attributes']['usagetype'],
                                'Location': item['product']['attributes']['location'],
                                'USD': self.price
                                }
        return self.pricing
        
    def price_list_EC2(self):
        self.response_pages('EC2')
        for item in self.price_item:
            terms = item['terms']
            if 'instanceType' in item['product']['attributes']:
                instance_type = item['product']['attributes']['instanceType']
                region = region_short_names[item['product']['attributes']['location']]

                if 'OnDemand' in terms:
                    self.onDemand_variables(terms, 'OnDemand')

                    if not instance_type in self.pricing[region]['EC2']:
                        self.pricing[region]['EC2'][instance_type] = {}

                    if not 'OnDemand' in self.pricing[region]['EC2'][instance_type]:
                        self.pricing[region]['EC2'][instance_type]['OnDemand'] = {}

                    usageType = item['product']['attributes']['usagetype']

                    if re.search('.*BoxUsage:{}'.format(instance_type),usageType):
                        self.pricing[region]['EC2'][instance_type]['OnDemand'] = {
                                'Description': self.description,
                                'UsageType': item['product']['attributes']['usagetype'],
                                'Location': item['product']['attributes']['location'],
                                'Tenancy': item['product']['attributes']['tenancy'],
                                'Operating System': item['product']['attributes']['operatingSystem'],
                                'USD': self.price
                                } 

                if 'Reserved' in terms:
                    for reserved_sku in terms['Reserved'].keys():
                        term_attributes = terms['Reserved'][reserved_sku]['termAttributes']
                        price_dimensions = terms['Reserved'][reserved_sku]['priceDimensions']
                        ri_purchase_option = term_attributes['PurchaseOption'] 

                        if not instance_type in self.pricing[region]['EC2']:
                            self.pricing[region]['EC2'][instance_type] = {}

                        if not 'Reserved' in self.pricing[region]['EC2'][instance_type]:
                            self.pricing[region]['EC2'][instance_type]['Reserved'] = {}

                        if not ri_purchase_option in self.pricing[region]['EC2'][instance_type]['Reserved']:
                            self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option] = {}

                        if term_attributes['OfferingClass'] == 'standard' and term_attributes['LeaseContractLength'] == '1yr':
                            if ri_purchase_option == 'Partial Upfront':
                                self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option] = {
                                    'QuantityRateCode': '',
                                    'HrsRateCode': '',
                                    'Offering_Class': term_attributes['OfferingClass'],
                                    'PurchaseOption': ri_purchase_option,
                                    'HrsUSD': '',
                                    'UpfrontFeeUSD': ''
                                }
                                for price_dimension in price_dimensions:
                                    if price_dimensions[price_dimension]['unit'] == 'Quantity':
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['UpfrontFeeUSD'] = price_dimensions[price_dimension]['pricePerUnit']['USD']
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['QuantityRateCode'] = price_dimensions[price_dimension]['rateCode']
                                    if price_dimensions[price_dimension]['unit']  == 'Hrs':
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['HrsUSD'] = price_dimensions[price_dimension]['pricePerUnit']['USD']
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['HrsRateCode'] = price_dimensions[price_dimension]['rateCode']
                            
                            if ri_purchase_option == 'All Upfront':
                                self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option] = {
                                    'QuantityRateCode': '',
                                    'HrsRateCode': '',
                                    'Offering_Class': term_attributes['OfferingClass'],
                                    'PurchaseOption': ri_purchase_option,
                                    'HrsUSD': '',
                                    'UpfrontFeeUSD': ''
                                }
                                for price_dimension in price_dimensions:
                                    if price_dimensions[price_dimension]['unit'] == 'Quantity':
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['UpfrontFeeUSD'] = price_dimensions[price_dimension]['pricePerUnit']['USD']
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['QuantityRateCode'] = price_dimensions[price_dimension]['rateCode']
                                    if price_dimensions[price_dimension]['unit']  == 'Hrs':
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['HrsUSD'] = price_dimensions[price_dimension]['pricePerUnit']['USD']
                                        self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['HrsRateCode'] = price_dimensions[price_dimension]['rateCode']
                            
                            if ri_purchase_option == 'No Upfront':
                                self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option] = {
                                    'RateCode': '',
                                    'Offering_Class': term_attributes['OfferingClass'],
                                    'PurchaseOption': ri_purchase_option,
                                    'USD': ''
                                }
                                for price_dimension in price_dimensions:
                                    self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['RateCode'] = price_dimensions[price_dimension]['rateCode']
                                    self.pricing[region]['EC2'][instance_type]['Reserved'][ri_purchase_option]['USD'] = price_dimensions[price_dimension]['pricePerUnit']['USD']
        return self.pricing       
     
price = pricing_info()