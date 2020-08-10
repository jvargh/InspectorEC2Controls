# InspectorEC2Controls

This repository provides an implementation of an AWS Inspector run. Prior to this run EC2 instances in the specified accounts are turned on, and stopped after the Inspector run has been completed.  

Two designs have been implemented, one using AWS Config to get EC2 data and the other by assuming Roles cross-accounts.

## *Using AWS Config*

To implement this in AWS Config an Aggregator was setup, which gets information on EC2 instances accounts defined in the AWS Organization. Boto3 API then sends an SQL query against the Aggregator, to get relevant EC2 data used in the code. Pros and Cons are as listed below

* <light style="color: green">(+) No need for roles setup across accounts hence simplifying administration</light>  
* <light style="color: green">(+) Prevents throttling at scale using EC2 API</light>
* <light style="color: lightcoral">(-) Delay on getting updates on resource status, for e.g. an EC2 stop takes 3-4m for status to reflect in a Config query. So corresponding delay needs to be built between stages in the workflow</light>

Lambda and Py implementation can be found in 'lambdaConfigAccess'. Py-Local was used for local dev and testing. 

## *Using Cross-Account Roles*

To implement this, cross-account Roles need to be setup in all accounts with appropriate control permissions for the EC2 instances. In code the STS API was then used to assume these roles and dynamically control EC2 depending on AWS region. Pros and Cons are listed below
* <light style="color: green">(+) Near realtime resource status updates can be retrieved by EC2 API</light>  
* <light style="color: lightcoral">(-) Used at scale will cause throttling of EC2 API, hence implementing retry/backoff if needed</light>  

Lambda and Py implementation can be found in 'lambdaCrossAccountAccess'. Py-Local was used for local dev and testing   

## *Highlights* ##

* [AWS Toolkit for VSCode ](https://docs.aws.amazon.com/toolkit-for-vscode/latest/userguide/welcome.html)was leveraged for development and testing. 
* [EC2 Boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.run_instances) for Python was leveraged. 
* DynamoDB Cfn template 'dynamodb-inspector.yaml' included in the repo, sets up the Instance and Exceptions tables, with supporting CLI commands in the Output section
* Common benefits involve EC2 batch start and stop API, and the [Waiters module](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#waiters) used to wait for a collective return when a specified state was reached.
* Single lambda to host Stop/Start/Inspector runs. Event inputs can be used to trigger workflow that needs to get executed. See sample launch.json in Lambda folder as an example.   

## *Output of a sample run*

The below output is common across both designs. 
- When Start-of-Stopped-Instances is called, existing entries from the DynamoDB Instance table gets dropped.   
- It then builds up a List 'stopped_instances_now_running' of all stopped instances that need to be started. List is then used to batch start EC2 and Waiter waits till 'instance_running' is reached  
- Sleep can be triggered by Step Fn to give time for started EC2's to settle
- Verification step then checks to see if EC2 instances in List are all stopped and if in any other state they get written to DynamoDB Instance table. 
- When Stopping-of-Running-Instances is called, first check is to the DynamoDB Exceptions table for entries and if so that instance is skipped from being shut down
- It then makes an API call to get all started instances, that does a batch shut down and Waiter waits till 'instance_stopped' is reached. 
- Call to Inspector Assessment template is done before instance shut down

![Sample run](/img/0-sample-run.jpg)

## *References*

Lambda cross account:<br>
https://medium.com/@it.melnichenko/invoke-a-lambda-across-multiple-aws-accounts-8c094b2e70be

Deep Dive: AWS AssumeRole using STS API:<br>
https://blog.knoldus.com/deep-dive-aws-temporary-security-credentials-assumerole-and-iam-role/

VS Code for AWS User guide:<br>
https://docs.aws.amazon.com/toolkit-for-vscode/latest/userguide/aws-tookit-vscode-ug.pdf#serverless-apps