# ServiceCatalog Product Enabler

## What is it?
Easily install a product from your ServiceCatalog portfolio on all the accounts of your organisation.
The tool supports hundreds of accounts.

## How it works
First install the CloudFormation template below:
 
`service-catalog-product-enabler.yaml`

The template will generate a CodeBuild project as well as a CodeCommit repository and a DynamoDb table to keep track.

| Created resources  | Resource name |
| ------------- | ------------- |
| CodeBuild project | ServiceCatalogProductEnabler  |
| CodeCommit repo  | ServiceCatalogProductEnabler  |
| DynamoDb table | service_catalog_product_enabler | 

 The CodeBuild project does all the logic.
 
 The Python script `service_catalog_product_enabler_init.py` initialize the data, by listing in the DynamoDb table the accounts of the organisation.
 A second script launches the different workers (a worker is a Python thread to perform the install).
 
 `service_catalog_product_enabler_launcher.py` (Threads launcher)
 `service_catalog_product_enabler_worker.py` (Thread class)
 
                 Is the role assigned
                to the portfolio?
                    +        +
                    |        |
                    |        | NO
                YES |        |
                    |        |
                    |        |
                    |        +----> Assign the role to the portfolio
                    |                    +
                    |                    |
                    |                    |
                    v                    |
            Check if the product is <----+
            already installed
                 +          +
                 |          |
              NO |          |YES
                 |          |
                 |          |
                 v          |
         Install product    |
                 +          |
                 |          |
                 |          |
                 |          |
                 |          |
                 v          v
           Finish account processing

 
 ## Requirements
 Create a role in all the organisation accounts so that the thread can assume it.
 This role will need the following policies:
 * servicecatalog:ListLaunchPaths
 * servicecatalog:AssociatePrincipalWithPortfolio
 * servicecatalog:ProvisionProduct
 * servicecatalog:SearchProvisionedProducts
 
 # Input parameters
 Parameters are provided in YAML file.
 The YAML file must be present in the CodeCommit repo.
 `ServiceCatalogProductEnabler/servicecatalog_product_enabler_conf.yml`
 
 Parameters list:

| Name  | Mandatory | Type | Description |
| ------------- | ------------- | ------------- | ------------- |
|portfolio_name|YES| string | The name of the portfolio containing the product to install|
|product_name|YES| string | The name of the product in the portfolio to be installed|
|role_for_product_install|YES | string | The role that has to be present in each account of the organization that performs the product install|
|dry_run|NO| boolean (default True) | When False product is provisioned |
|tags* | NO | object | The tags you want to configure on resources |
|workers_number|NO|number (default is 20) | The number of thread to use|
|target_regions|NO|array(string)| If you want to target only some specific regions |
|no_go_regions|NO|array(string)| If you want  to exclude some regions |
|no_go_accounts|NO|array(string)| If you want to exclude some specific accounts|
|aws_service_name|NO|string| In case you want to select the regions where a specific service is present. For example if you put 'config' as value it will select as target regions only those where service config is present.|

tags parameter example (YAML):
```
tags:
  - Key: 'CCOEBaseline'
    Value:  'True'`
```



