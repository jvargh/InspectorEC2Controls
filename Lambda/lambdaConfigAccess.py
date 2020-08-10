import json
import logging
import time
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError, WaiterError

LOG = logging.getLogger(__name__)

def GetAwsConfigData(config_cli, account_id): 
    ec2_instances=[]

    # Pg. 227 on: https://docs.amazonaws.cn/en_us/config/latest/developerguide/config-dg.pdf
    config_res = config_cli.select_aggregate_resource_config( 
        ConfigurationAggregatorName='EC2_Instances_within_an_Account',
        Expression='SELECT accountId, awsRegion, resourceId, configuration.state, tags \
                    WHERE resourceType = \'AWS::EC2::Instance\' and \
                    accountId = \''+ account_id +'\'' 
    )

    for instance in config_res['Results']:
        val = json.loads(instance)    
        instanceId = val['resourceId']
        instanceState = val['configuration']['state']['name']
        instanceName = ''

        for val in val['tags']: 
            if(val['key']=='Name'):
                instanceName = val['value']

        ec2_instances.append({'instanceId':instanceId, 'instanceState':instanceState, 'instanceName':instanceName})

    return ec2_instances


def StartStoppedInstances( ec2_instances, ec2_con_cli ):

    stopped_instances_now_running=[]

    for instance in ec2_instances: 
        instanceName = instance['instanceName']
        instanceId = instance['instanceId']
        instanceState = instance['instanceState']

        test_instances=['SSM-Test', 'SSMRedhat', 'SSMWin2019']  # test only

        if (instanceName not in test_instances): # test only
            continue

        if (instanceState=='running'):
            print('Running: ', instanceId, ' : ', instanceName)
            continue
        elif (instanceState=='stopped'):
            print('Stopped: ', instanceId, ' : ', instanceName)
            stopped_instances_now_running.append(instanceId)

    if stopped_instances_now_running:
        print('Starting instances: ', stopped_instances_now_running)
        ec2_con_cli.start_instances(InstanceIds=stopped_instances_now_running)

        # 40 checks every 15s. https://github.com/boto/botocore/blob/master/botocore/data/ec2/2016-11-15/waiters-2.json
        waiter=ec2_con_cli.get_waiter('instance_running') 

        try:
            waiter.wait(InstanceIds=stopped_instances_now_running)
            print('Instances are up and running')
        except WaiterError as e:
            LOG.debug("Waiter failed: ", exc_info=e)
            pass

    return stopped_instances_now_running


def VerifyStoppedInstancesAreRunning(ec2_instances, stopped_instances_now_running, table):
    for instance in ec2_instances: 
        instanceName = instance['instanceName']
        instanceId = instance['instanceId']
        instanceState = instance['instanceState']

        if(instanceId not in stopped_instances_now_running):
            continue
        else: 
            if(instanceState == 'running'):
                print('Skipping: ',instanceId,"__",instanceName)
                continue
            else: 
                # Write to DynamoDB
                print('Writing to DB: ',instanceId,"__",instanceName)
                instance_data = {
                    'InstanceId': instanceId,
                    'AccountId': account_id,
                    'InstanceRegion': region_name_
                }
                table.put_item(Item=instance_data)

def StopRunningInstances(ec2_instances, ec2_con_cli, table_exc):

    running_instances_now_stopped=[]

    for instance in ec2_instances: 
        instanceName = instance['instanceName']
        instanceId = instance['instanceId']
        instanceState = instance['instanceState']

        test_instances=['SSMRedhat', 'SSMWin2019']  # test only

        # If InstanceId is in Exceptions Table then don't stop intance
        resp = table_exc.query(KeyConditionExpression=Key('InstanceId').eq(instanceId))
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
        print('Stopping instances: ', running_instances_now_stopped)
        ec2_con_cli.stop_instances(InstanceIds=running_instances_now_stopped)

        # 40 checks every 15s. https://github.com/boto/botocore/blob/master/botocore/data/ec2/2016-11-15/waiters-2.json
        waiter=ec2_con_cli.get_waiter('instance_stopped') 

        try:
            waiter.wait(InstanceIds=running_instances_now_stopped)
            print('Running instances have now been Stopped')
        except WaiterError as e:
            LOG.debug("Waiter failed: ", exc_info=e)
            pass

    return running_instances_now_stopped    


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
        print('Assessment is now being run...')
        response = inspect_client.start_assessment_run(assessmentTemplateArn=template_arn, assessmentRunName='assessment_run_'+now.strftime("%m-%d-%Y_%H:%M:%S") )
        # print(response)
    except Exception as e:
        print(e)
        pass
            

def lambda_handler(event, context):
    # Initialize
    account_id=event.get('account_id')
    region_name_=event.get('region_name')
    insp_assmt_template_arn=event.get('insp_assmt_template_arn')
    action=event.get('action')

    session = boto3.session.Session()
    ec2_con_cli = session.client("ec2", region_name=region_name_)
    inspect_client = boto3.client('inspector', region_name=region_name_)
    config_cli = boto3.client('config')

    dynamodb_res = boto3.resource('dynamodb', region_name=region_name_)
    table = dynamodb_res.Table('Inspector-Started-Instances')
    table_exc = dynamodb_res.Table('Inspector-Exceptions')

    # Start here    
    if (action=="start"):
        print('Starting Stopped Instances in Region=',region_name_,', Account=',account_id)
        stopped_instances_now_running = StartStoppedInstances( GetAwsConfigData(config_cli,account_id), ec2_con_cli )

        print('Sleeping for 3m...')
        time.sleep(180)
        
        print('Verifying Stopped Instances in Region=',region_name_,', Account=',account_id)
        VerifyStoppedInstancesAreRunning( GetAwsConfigData(config_cli,account_id), stopped_instances_now_running, table)

    elif (action=="stop"):
        print('Stopping Started Instances in Region=',region_name_,', Account=',account_id)
        StopRunningInstances( GetAwsConfigData(config_cli,account_id), ec2_con_cli, table_exc)

    elif (action=="inspect"):        
        print('Starting Inspector in Region=',region_name_,', Account=',account_id)
        InspectAllInstances( insp_assmt_template_arn, inspect_client )
