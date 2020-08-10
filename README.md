# InspectorEC2Controls

Purpose of this repository is to provide an implementation of an AWS Inspector run, cross-accounts in specified regions. Prior to this run EC2 instances in the account are turned on and shutdown after the Inspector run has bene completed.  

Two designs have been implemented, one using AWS Config and the other by assuming Roles cross-accounts. 

## *Using AWS Config*

To implement this in AWS Config an Aggregator was setup, which gets information on EC2 instances in accounts under the AWS Organization. Boto3 API calls were then used to send an SQL query to get relevant EC2 data used in the code. Pros and Cons are listed below

* <light style="color: green">(+) No need for roles setup across accounts</light>  
* <light style="color: green">(+) Prevents throttling at scale as the case with using EC2 API</light>
* <light style="color: lightcoral">(-) Delay on getting updates on resource status, for e.g. an EC2 stop takes 3-4m for status to reflect in a Config query. So corresponding delay needs to be built between stages in the workflow</light>

Lambda and Py implementation can be found in 'lambdaConfigAccess'. Py-Local was used for local dev and testing. 

## *Using Cross-Account Roles*

To implement this cross-account Roles need to be setup in all accounts with appropriate control permissions for the EC2 instances. In code the STS API was then used to assume these roles and dynamically control EC2 depending on AWS region. Pros and Cons are listed below
* <light style="color: green">(+) Near realtime resource status updates can be retrieved by EC2 API</light>  
* <light style="color: lightcoral">(-) Used at scale will cause throttling of EC2 API, hence implementing retry/backoff if needed</light>  

Lambda and Py implementation can be found in 'lambdaCrossAccountAccess'. Py-Local was used for local dev and testing   

## *Highlights* ##

* [AWS Toolkit for VSCode ](https://docs.aws.amazon.com/toolkit-for-vscode/latest/userguide/welcome.html)was leveraged for development and testing. 
* [EC2 Boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.run_instances) for Python was leveraged. 
* DynamoDB Cfn template 'dynamodb-inspector' sets up the Instance and Exceptions tables, with supporting commands in the Output section
* Common benefits came about by using EC2 batch start and stop API, and the [Waiters module](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#waiters) was used to wait for a collective return of resources when a specified state was reached.
* Single lambda to host Stop/Start/Inspector runs. Event inputs can be used to trigger what needs to get executed, see sample launch.json as an example.   

## *Output of a sample run*

The below output is common across both designs. 
- When Start-of-Stopped-Instances is called, existing entries from the DynamoDB Instance table gets dropped.   
- It then builds up a List 'stopped_instances_now_running' of all stopped instances that need to be started. List is then used to batch start and Waiter waits till 'instance_running' is reached  
- Sleep can be triggered by Step Fn to give time for all started EC2's to settle
- Verification step then checks to see if EC2 instances in List are all stopped and if in any other state they get written to DynamoDB Instance table. 
- When Stopping-of-Running-Instances is called, first check is to the DynamoDB Exceptions table for entry and if so that instance is skipped from being shut down
- It then makes an API call to get all started instances, that batch shuts down and Waiter waits till 'instance_stopped' is reached. 
- Call to Inspector Assessment template is done before instance shut down

![Sample run](/img/sample-run.jpg)