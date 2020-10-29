import boto3
from botocore.exceptions import ClientError
import time


table_name = 'service_catalog_product_enabler'
org_cli = boto3.client('organizations')
db_cli = boto3.client('dynamodb')

paginator = org_cli.get_paginator('list_accounts')

pages = paginator.paginate()

try:
    db_cli.create_table(
        AttributeDefinitions=[
            {
                'AttributeName': 'AccountId',
                'AttributeType': 'S'
            },
        ],
        TableName=table_name,
        KeySchema=[
            {
                'AttributeName': 'AccountId',
                'KeyType': 'HASH'
            },
        ],
        ProvisionedThroughput={
            'ReadCapacityUnits': 5,
            'WriteCapacityUnits': 5
        },
    )
    still_creating = True
    while still_creating:
        time.sleep(5)
        response = db_cli.describe_table(TableName=table_name)
        if response['Table']['TableStatus'] == 'ACTIVE':
            still_creating = False

except ClientError as e:
    print(e.response)
    if e.response['Error']['Code'] == 'ResourceInUseException':
        print("Table exists, loading data into tables.")
    else:
        print("Unexpected error: %s" % e)
        exit(1)

for page in pages:
    if "Accounts" in page.keys():
        for account in page['Accounts']:
            if account['Status'] == 'ACTIVE':
                db_cli.put_item(TableName=table_name,
                                Item={

                                    'AccountId': {
                                        'S': account['Id']
                                    },
                                    'Processed': {
                                        'BOOL': False
                                    },
                                    'Locked': {
                                        'BOOL': False
                                    },
                                    'Error': {
                                        'BOOL': False
                                    },
                                }
                                )


