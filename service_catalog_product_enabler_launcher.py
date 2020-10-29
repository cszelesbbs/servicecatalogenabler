import os
import yaml

from service_catalog_product_enabler_worker import *

configuration_file = os.environ['SC_ENABLER_CONF']
with open(configuration_file, 'r') as stream:
    input_config = yaml.safe_load(stream)
no_go_accounts = input_config['no_go_accounts']
no_go_regions = input_config['no_go_regions']

portfolio_name = input_config['portfolio_name']
product_name = input_config['product_name']

product_version = None
if 'product_version' in input_config:
    product_version = input_config['product_version']

tags = None
if 'tags' in input_config:
    tags = input_config['tags']

dry_run = True
if 'dry_run' in input_config:
    dry_run = input_config['dry_run']

role_for_product_install = input_config['role_for_product_install']

workers_number = None
if 'workers_number' in input_config.keys() and input_config['workers_number'] and 0 < input_config[
    'workers_number'] < 21:
    workers_number = input_config['workers_number']
else:
    workers_number = 1

target_regions = []
if 'target_regions' in input_config.keys():
    target_regions = input_config['target_regions']

# if target regions parameter is not defined check if parameter "aws_service_name" is defined.
# "aws_service_name" will be used to retrieve the regions in which this aws service is present
if not (target_regions and len(target_regions) > 0):
    if not ('aws_service_name' in input_config and input_config['aws_service_name']):
        logging.warning("None of the following parameters were provided: target_regions, aws_service_name")
        exit(1)
    print("Trying to retrieve regions list for the service: " + input_config['aws_service_name'])
    try:
        target_regions = boto3.session.Session().get_available_regions(input_config['aws_service_name'])
    except Exception as e:
        error_message = "It was not possible to retrieve a target_regions list given the provided AWS service."
        logging.error(error_message)
        exit(1)

if len(target_regions) - len(no_go_regions) == 0:
    error_message = "No regions to work on. Review your target_regions and no_go_regions parameters."
    logging.error(error_message)
    exit(1)

service_catalog_regions = boto3.session.Session().get_available_regions('servicecatalog')

portfolios_ids = {}
products = {}

for sc_region in service_catalog_regions:
    if sc_region in target_regions and sc_region not in no_go_regions:

        sc_client = boto3.client('servicecatalog', region_name=sc_region)

        portfolio_found = False
        try:
            paginator = sc_client.get_paginator('list_portfolios')
            pages = paginator.paginate()
        except Exception as e:
            logging.error("region " + sc_region + " while calling API to list portfolios")
            exit(1)
        for page in pages:
            for portfolio in page['PortfolioDetails']:
                if portfolio['DisplayName'] == portfolio_name:
                    portfolios_ids[sc_region] = portfolio['Id']
                    portfolio_found = True
                    try:
                        paginator = sc_client.get_paginator('search_products_as_admin')
                        pages = paginator.paginate(PortfolioId=portfolio['Id'],
                                                   Filters={'FullTextSearch': [product_name]})
                        for page in pages:
                            if len(page['ProductViewDetails']) == 1:
                                product = page['ProductViewDetails'][0]
                                products[sc_region] = {}
                                products[sc_region]['id'] = product['ProductViewSummary']['ProductId']
                                desc_res = sc_client.describe_product_as_admin(Id=products[sc_region]['id'])
                                # Get ID of the product version. By default it takes the last version
                                if product_version and product_version > 0:
                                    if len(desc_res['ProvisioningArtifactSummaries']) >= product_version:
                                        product_version = product_version - 1
                                    else:
                                        logging.error('the product version you provided is not defined.')
                                        exit(1)
                                else:
                                    product_version = len(desc_res['ProvisioningArtifactSummaries']) - 1
                                products[sc_region]['product_artifact_id'] = \
                                    desc_res['ProvisioningArtifactSummaries'][product_version]['Id']
                                product_found = True
                            if product_found:
                                break
                        if not product_found:
                            logging.error(
                                "The product is not defined for the region " + sc_region + " and portfolio id: " +
                                portfolio['Id'])
                            exit(1)
                    except Exception as e:
                        logging.error(e)
                        exit(1)
                    break
            if portfolio_found:
                break
        if not portfolio_found:
            logging.error("The portfolio is not defined for the region " + sc_region)
            exit(1)

my_threads = []

for i in range(0, workers_number):
    my_threads.append(ConfigEnablerWorker(portfolios_ids=portfolios_ids,
                                          products=products,
                                          product_name=product_name,
                                          target_regions=target_regions,
                                          service_catalog_regions=service_catalog_regions,
                                          role_for_product_install=role_for_product_install,
                                          dry_run=dry_run,
                                          no_go_accounts=no_go_accounts,
                                          no_go_regions=no_go_regions,
                                          tags=tags)
                      )
    my_threads[i].start()

for i in range(0, workers_number):
    my_threads[i].join()
