# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
import json
import logging
import time
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError, WaiterError

LOG = logging.getLogger(__name__)

# used to clear items in table
def delete_table_items(table):
    try:
        scan = table.scan()
        with table.batch_writer() as batch:
            for each in scan['Items']:
                batch.delete_item(
                    Key={
                        'InstanceId': each['InstanceId']
                    }
                )    
        print('\nTable items deleted.\n')
    except Exception as e:
        print('\nTable delete exception: ', e)

# used to start all stopped instances
def StartStoppedInstances( ec2_con_cli, table_inst, account_id ):

    # used to collect stopped instances that are now running by the end
    stopped_instances_now_running=[]

    # Clear Instances table
    delete_table_items(table_inst)

    # Define EC2 filters. Pass in AccountID to get EC2 in just this account
    f0= {"Name": "owner-id", "Values":[account_id]}
    f1= {"Name" : "instance-state-name", "Values" : ['running','stopped']}
    f2= {"Name" : "tag:Name", "Values" : ['SSM-Test','SSMRedhat','SSMWin2019']}  # for test only      

    for each_item in ec2_con_cli.describe_instances(Filters=[f0, f1, f2])['Reservations']:
        for instance in each_item['Instances']:
            instanceState = instance['State']['Name']
            instanceId = instance['InstanceId']
            instanceName = ''
            for val in instance['Tags']: 
                if(val['Key']=='Name'):
                    instanceName = val['Value']      

            if(instanceState=='running'):
                print('Running: ', instanceId, ' : ', instanceName)
                continue
            elif(instanceState=='stopped'):
                print('Stopped: ', instanceId, ' : ', instanceName)
                stopped_instances_now_running.append(instanceId)
    
    # if no entries i.e. all instances running then skip
    if stopped_instances_now_running:
        print('Starting instances: ', stopped_instances_now_running)
        ec2_con_cli.start_instances(InstanceIds=stopped_instances_now_running)

        # 40 checks every 15s. https://github.com/boto/botocore/blob/master/botocore/data/ec2/2016-11-15/waiters-2.json
        # wait till all instances in list are in RUNNING state
        waiter=ec2_con_cli.get_waiter('instance_running') 

        try:
            waiter.wait(InstanceIds=stopped_instances_now_running)
            print('Instances are up and running')
        except WaiterError as e:
            LOG.debug("Waiter failed: ", exc_info=e)
            pass

    return stopped_instances_now_running

# used to verify all started instances in list are started not stopped else write to DB
def VerifyStoppedInstancesAreRunning(ec2_con_cli, stopped_instances_now_running, table_inst, account_id, region_name_):

    # Define EC2 filters
    f0= {"Name": "owner-id", "Values":[account_id]}
    f1= {"Name" : "instance-state-name", "Values" : ['running','stopped']}
    f2= {"Name" : "tag:Name", "Values" : ['SSM-Test','SSMRedhat','SSMWin2019']}  # for test only      

    for each_item in ec2_con_cli.describe_instances(Filters=[f0, f1, f2])['Reservations']:
        for instance in each_item['Instances']:
            instanceState = instance['State']['Name']
            instanceId = instance['InstanceId']
            instanceName = ''
            for val in instance['Tags']: 
                if(val['Key']=='Name'):
                    instanceName = val['Value']      

            if(instanceId not in stopped_instances_now_running):
                continue
            else: 
                if(instanceState == 'running'):
                    print('(Good) Running: ',instanceId,"__",instanceName)
                    continue
                else: 
                    # Write to DynamoDB if instances in list are in any state other than RUNNING
                    print('(Bad) Stopped: ',instanceId,"__",instanceName,'. Writing to DB.')
                    instance_data = {
                        'InstanceId': instanceId,
                        'AccountId': account_id,
                        'InstanceRegion': region_name_
                    }
                    table_inst.put_item(Item=instance_data)

# used to stop all started instances
def StopRunningInstances(ec2_con_cli, table_excp, account_id ):

    running_instances_now_stopped=[]

    # Define EC2 filters
    f0= {"Name" : "owner-id", "Values":[account_id]}
    f1= {"Name" : "instance-state-name", "Values" : ['running','stopped']}
    f2= {"Name" : "tag:Name", "Values" : ['SSM-Test','SSMRedhat','SSMWin2019']}  # for test only      

    for each_item in ec2_con_cli.describe_instances(Filters=[f0, f1, f2])['Reservations']:
        for instance in each_item['Instances']:
            instanceState = instance['State']['Name']
            instanceId = instance['InstanceId']
            instanceName = ''
            for val in instance['Tags']: 
                if(val['Key']=='Name'):
                    instanceName = val['Value']      

            test_instances=['SSMRedhat', 'SSMWin2019']  # test only

            # If InstanceId is in Exceptions Table then don't stop intance
            resp = table_excp.query(KeyConditionExpression=Key('InstanceId').eq(instanceId))
            if (resp['Items']):
                if(resp['Items'][0]['InstanceId']):
                    print('Skipping RUNNING instance: ', instanceId, ' : ', instanceName)
                    continue

            # If Instance is in Test list then skip        
            if (instanceName not in test_instances): # test only
                continue

            # Skip if instances are in Stopped state else add to List    
            if (instanceState=='stopped'):
                print('Stopped: ', instanceId, ' : ', instanceName)
                continue
            elif (instanceState=='running'):
                print('Running: ', instanceId, ' : ', instanceName)
                running_instances_now_stopped.append(instanceId)

    # Stop all instances in list
    if running_instances_now_stopped:
        print('\nStopping instances: ', running_instances_now_stopped)
        ec2_con_cli.stop_instances(InstanceIds=running_instances_now_stopped)

        # 40 checks every 15s. https://github.com/boto/botocore/blob/master/botocore/data/ec2/2016-11-15/waiters-2.json
        # wait till all instances in list are in STOPPED state
        waiter=ec2_con_cli.get_waiter('instance_stopped') 

        try:
            waiter.wait(InstanceIds=running_instances_now_stopped)
            print('\nRunning instances have now been Stopped')
        except WaiterError as e:
            LOG.debug("Waiter failed: ", exc_info=e)
            pass

    return running_instances_now_stopped    

# used to inspect all started instances using the pre-configured assessment template in AWS Inspector
def InspectAllInstances(template_arn, inspect_client):    
    now = datetime.now()
    try:        
        templates = inspect_client.describe_assessment_templates(
            assessmentTemplateArns=[
                template_arn
            ]        
        )
        print("\nInspector Assessment Template used: ", templates, "\n")

        # run assessment       
        assessment_name = 'assessment_run_'+now.strftime("%m-%d-%Y_%H:%M:%S")
        print("Assessment ("+assessment_name+") is now being run...")
        response = inspect_client.start_assessment_run(assessmentTemplateArn=template_arn, assessmentRunName=assessment_name )
        # print(response)
    except Exception as e:
        print(e)
        pass
            
# main- start here
def lambda_handler(event, context):
    # Initialize- get data from event
    account_id=event.get('account_id')
    region_name_=event.get('region_name')
    insp_assmt_template_arn=event.get('insp_assmt_template_arn')
    action=event.get('action')
    role_arn=event.get('role_arn')

    # Get Session by getting Credentials from Assumed Role    
    session = boto3.session.Session()
    sts_client = session.client('sts')
    assumed_role = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName="testSession",
        ExternalId="testcrossaccountddb" # <ExternalID that you have defined in Account A>
    )
    credentials = assumed_role['Credentials']
    ec2_con_cli = boto3.client('ec2', region_name=region_name_, aws_access_key_id=credentials['AccessKeyId'],
                    aws_secret_access_key=credentials['SecretAccessKey'],
                    aws_session_token=credentials['SessionToken'])

    # DynamoDB client
    dynamodb_res = boto3.resource('dynamodb', region_name=region_name_)
    table_inst = dynamodb_res.Table('Inspector-Started-Instances')
    table_excp = dynamodb_res.Table('Inspector-Exceptions')

    # Inspector client
    inspect_client = boto3.client('inspector', region_name=region_name_)
    
    # Start here    
    if (action=="start"):
        print('\n<< Starting Stopped Instances in Region=',region_name_,', Account=',account_id,' >>')
        # Get EC2 data from Config query and pass to fn to examine if Stopped and if so Start
        stopped_instances_now_running = StartStoppedInstances( ec2_con_cli, table_inst, account_id)

        # Give enough time for EC2's to settle down 
        print('\nSleeping for 2m...')
        time.sleep(120)
        
        print('\n<< Verifying Stopped Instances in Region=',region_name_,', Account=',account_id,' >>')
        VerifyStoppedInstancesAreRunning( ec2_con_cli, stopped_instances_now_running, table_inst, account_id, region_name_)

    elif (action=="stop"):
        print('\n<< Stopping Started Instances in Region=',region_name_,', Account=',account_id,' >>')
        StopRunningInstances( ec2_con_cli, table_excp, account_id )

    elif (action=="inspect"):        
        print('\n<< Starting Inspector in Region=',region_name_,', Account=',account_id,' >>')
        InspectAllInstances( insp_assmt_template_arn, inspect_client )
