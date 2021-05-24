from datetime import datetime
import json
import boto3

rds_client = boto3.client('rds-data')

cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'

def lambda_handler(event, context):
    from_datetime = datetime.strptime(event['queryStringParameters']['start_date'], "%Y-%m-%dT%H:%M:00.000Z")
    to_datetime = datetime.strptime(event['queryStringParameters']['end_date'], "%Y-%m-%dT%H:%M:00.000Z")
    
    sql = (
        "select i.id, i.time_created, it.tag "
        "from images i "
        "left join image_tag it on it.image_id = i.id "
        "where time_created >= :from_datetime and time_created < :to_datetime"
    )
    response = rds_client.execute_statement(
        resourceArn = cluster_arn, 
        secretArn = secret_arn, 
        database = database, 
        sql = sql,
        parameters = [
            {
                'name': 'from_datetime',
                'typeHint': 'TIMESTAMP',
                'value': {'stringValue': str(from_datetime)}
            },
            {
                'name': 'to_datetime',
                'typeHint': 'TIMESTAMP',
                'value': {'stringValue': str(to_datetime)}
            },
        ]
    )
    images = []
    last_image = None
    for record in response['records']:
        if not last_image or last_image['id'] != record[0]['stringValue']:
            if last_image:
                images.append(last_image)
            last_image = {'id': record[0]['stringValue'], 'timeCreated': record[1]['stringValue'], 'tags': []}

        if 'stringValue' in record[2]:
            last_image['tags'].append(record[2]['stringValue'])
    images.append(last_image)

    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
        },
        'body': json.dumps({'images': images})
    }