from threading import Thread, RLock
import threading
import boto3
import uuid
import logging
import botocore

lock = RLock()


class ConfigEnablerWorker(Thread):
    def __init__(self,
                 portfolios_ids,
                 products,
                 target_regions,
                 service_catalog_regions,
                 product_name,
                 role_for_product_install,
                 dry_run,
                 no_go_accounts=None,
                 no_go_regions=None,
                 tags=None):
        Thread.__init__(self)
        self.db_cli = boto3.client('dynamodb')
        self.sts_cli = boto3.client('sts')
        self.table_name = 'service_catalog_product_enabler'
        self.table_name_verification = 'service_catalog_product_enabler_verification'
        self.product_name = product_name
        self.target_regions = target_regions
        self.service_catalog_regions = service_catalog_regions
        self.no_go_accounts = no_go_accounts
        self.no_go_regions = no_go_regions
        self.portfolios_ids = portfolios_ids
        self.products = products
        self.role_for_product_install = role_for_product_install
        self.dry_run = dry_run
        self.tags = tags

    def data_access_put(self, account_id, error, processed, locked, description=''):
        # Set Error to True, no need to lock the thread here because the item is already locked
        return self.db_cli.put_item(TableName=self.table_name,
                                        Item={

                                            'AccountId': {
                                                'S': account_id
                                            },
                                            'Error': {
                                                'BOOL': error
                                            },
                                            'Processed': {
                                                'BOOL': processed
                                            },
                                            'Locked': {
                                                'BOOL': locked
                                            },
                                            'Description': {
                                                'S': description
                                            }
                                        }
                                )

    def change_lock(self, account_id, lock_mode):
        # Set processed to True, no need to lock the thread here because the item is already locked
        return self.db_cli.update_item(TableName=self.table_name,
                                           ExpressionAttributeNames={
                                               '#LO': 'Locked'
                                           },
                                           ExpressionAttributeValues={
                                               ':f': {
                                                   'BOOL': lock_mode,
                                               },
                                           },
                                           Key={
                                               'AccountId': {
                                                   'S': account_id
                                               }
                                           },
                                           UpdateExpression='SET #LO = :f',
                                           )

    def set_account_error(self, account_id, description=''):
        # Set Error to True, no need to lock the thread here because the item is already locked
        return self.data_access_put(account_id, error=True, processed=False, locked=False, description=description)

    def set_account_processed(self, account_id, description=''):
        # Set processed to True, no need to lock the thread here because the item is already locked
        return self.data_access_put(account_id, error=False, processed=True, locked=False, description=description)

    def run(self):
        while True:
            account_skipped = False
            account_failed = False

            # getting account id from db and lock item
            with lock:
                try:
                    response = self.db_cli.scan(
                        TableName=self.table_name,
                        ConsistentRead=True,
                        FilterExpression='#locked=:false AND #processed=:false AND #error=:false',
                        ExpressionAttributeNames={
                            "#locked": "Locked",
                            "#processed": "Processed",
                            "#error": "Error"
                        },
                        ExpressionAttributeValues={
                            ":false": {"BOOL": False},

                        }
                    )
                except botocore.exceptions.ClientError as error:
                    logging.error(error.response['Error']['Code'] + " - problem accessing Dynamodb table.")
                    exit(1)

                if response['Count'] > 0:
                    account_id = response['Items'][0]['AccountId']['S']

                    if account_id in self.no_go_accounts:
                        logging.error("NoGo account: " + account_id + ", skipping.")
                        self.set_account_processed(account_id=account_id, description="NoGo account")
                        continue

                    # Lock account in the DB
                    self.change_lock(account_id=account_id, lock_mode=True)
                else:
                    print("No more accounts to be processed. Exiting Thread.")
                    exit(0)
                    # no more elements to be processed
                    return
            # End of non-concurrent area

            description = None
            if self.dry_run:
                print("Dry-run execution")

            # this role is used to install the product. The role must exist in the target accounts.
            role_arn = 'arn:aws:iam::' + account_id + ':role/' + self.role_for_product_install
            try:
                assumed_role = self.sts_cli.assume_role(
                    DurationSeconds=3600,
                    ExternalId=str(uuid.uuid4()),
                    RoleArn=role_arn,
                    RoleSessionName="SessionForThread" + str(threading.get_ident()),
                )
            except Exception as e:
                logging.error(e)
                description = "cannot assume role " + self.role_for_product_install + " on account " + account_id
                logging.error(description)
                account_failed = True

            if not account_failed:
                # For each region in which both config and service catalog are supported verify Config product in SC
                for sc_region in self.service_catalog_regions:
                    if sc_region in self.target_regions and sc_region not in self.no_go_regions:
                        session = boto3.session.Session(aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                                                        aws_secret_access_key=assumed_role['Credentials'][
                                                            'SecretAccessKey'],
                                                        aws_session_token=assumed_role['Credentials']['SessionToken'])
                        sc_cli = session.client('servicecatalog', region_name=sc_region)
                        #cf_cli = session.client('config', region_name=sc_region)

                        try:
                            response = sc_cli.search_provisioned_products(
                                AccessLevelFilter={
                                    'Key': 'Account',
                                    'Value': 'self'
                                },
                                Filters={'SearchQuery': ["productId:" + self.products[sc_region]['id']]}
                            )
                        except botocore.exceptions.ClientError as error:
                            account_failed = True
                            logging.error(error)
                            description= account_id + ", region: " + sc_region + ". " + error.response['Error']['Code']
                            logging.error(description)
                            break

                        if len(response['ProvisionedProducts']) == 0:
                            # look if a config is already present
                            #response = cf_cli.describe_delivery_channels()
                            if True:
                                # install Service Catalog product
                                print("Installing SG product for account id: " + account_id + " and region " + sc_region)
                                # Assign role constraint to imported portfolio
                                try:
                                    sc_cli.associate_principal_with_portfolio(
                                        PortfolioId=self.portfolios_ids[sc_region],
                                        PrincipalARN=role_arn,
                                        PrincipalType='IAM'
                                    )

                                    launch_res = sc_cli.list_launch_paths(ProductId=self.products[sc_region]['id'])
                                    if len(launch_res['LaunchPathSummaries']) == 0:
                                        raise Exception("No Launch path defined.")

                                    if not self.dry_run:
                                        sc_cli.provision_product(ProductId=self.products[sc_region]['id'],
                                                                 ProvisionedProductName=self.product_name,
                                                                 ProvisioningArtifactId=self.products[sc_region]['product_artifact_id'],
                                                                 PathId=launch_res['LaunchPathSummaries'][0]['Id'],
                                                                 Tags=self.tags)
                                        description = "Product installed"
                                    else:
                                        description = "dry-run"
                                except botocore.exceptions.ClientError as error:
                                    account_failed = True
                                    logging(error)
                                    description = account_id + ", region: " + sc_region + ". " + error.response['Error']['Code']
                                    break
                                except Exception as e:
                                    account_failed = True
                                    description = "region: " + sc_region + ": " + str(e)
                                    break
                        elif response['ProvisionedProducts'][0]['Status'] == "ERROR" or response['ProvisionedProducts'][0]['Status'] == "TAINTED":
                            description = "region: " + sc_region + ": already installed with status: " + response['ProvisionedProducts'][0]['Status']
                            account_failed = True
                            break
                        elif response['ProvisionedProducts'][0]['Status']:
                            description = "region: " + sc_region + ": already installed with status: " + response['ProvisionedProducts'][0]['Status']
            if account_failed:
                self.set_account_error(account_id, description=description)
            else:
                self.set_account_processed(account_id, description=description)

