import boto3
import json

rds_client = boto3.client('rds-data')

cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'

def lambda_handler(event, context):
    print(event)

    image_id = event['queryStringParameters']['image_id']
    tags = json.loads(event['body'])
    print(tags)

    rds_client.execute_statement(
        resourceArn = cluster_arn,
        secretArn = secret_arn,
        database = database,
        sql = 'delete from image_tag where image_id = :id',
        parameters = [
            {
                'name': 'id',
                'value': {'stringValue': image_id}
            },
        ]
    )

    for tag in tags:
        print(tag)
        rds_client.execute_statement(
            resourceArn = cluster_arn,
            secretArn = secret_arn,
            database = database,
            sql = 'insert into image_tag (image_id, tag) values (:id, :tag)',
            parameters = [
                {
                    'name': 'id',
                    'value': {'stringValue': image_id}
                },
                {
                    'name': 'tag',
                    'value': {'stringValue': tag}
                },
            ]
        )

    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,PUT,GET',
        },
    }