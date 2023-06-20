from datetime import datetime
import json
import boto3
import botocore

rds_client = boto3.client('rds-data')

cluster_arn = 'arn:aws:rds:eu-west-2:306578912108:cluster:database-1'
secret_arn = 'arn:aws:secretsmanager:eu-west-2:306578912108:secret:rds-db-credentials/cluster-QBRFG6NNVJEGKYGGMCDHRUGXVA/admin-F2AjV8' 
database = 'photoarchive'

def lambda_handler(event, context):
    where_clauses = []
    where_params = []
    if event['queryStringParameters']:
        if 'start_date' in event['queryStringParameters']:
            from_datetime = datetime.strptime(event['queryStringParameters']['start_date'], "%Y-%m-%dT%H:%M:00.000Z")
            where_clauses.append('time_created >= :from_datetime')
            where_params.append({
                'name': 'from_datetime',
                'typeHint': 'TIMESTAMP',
                'value': {'stringValue': str(from_datetime)}
            })
        if 'end_date' in event['queryStringParameters']:
            to_datetime = datetime.strptime(event['queryStringParameters']['end_date'], "%Y-%m-%dT%H:%M:00.000Z")
            where_clauses.append('time_created < :to_datetime')
            where_params.append({
                'name': 'to_datetime',
                'typeHint': 'TIMESTAMP',
                'value': {'stringValue': str(to_datetime)}
            })
        if 'tag' in event['multiValueQueryStringParameters']:
            tag_num = 1
            for tag in event['multiValueQueryStringParameters']['tag']:
                where_clauses.append(f'tag = :tag_{tag_num}')
                where_params.append({
                    'name': f'tag_{tag_num}',
                    'value': {'stringValue': tag}
                })
                tag_num += 1
        if 'photographer' in event['queryStringParameters']:
            photographer = event['queryStringParameters']['photographer']
            where_clauses.append("im.type = 'photographer' and im.value = :photographer")
            where_params.append({
                'name': 'photographer',
                'value': {'stringValue': photographer}
            })

    sql = (
        "select i2.id, i2.time_created, it2.tag, im2.type, im2.value "
        "from images i2 "
        "left join image_tag it2 on it2.image_id = i2.id "
        "left join image_metadata im2 on im2.image_id = i2.id "
        "where i2.id in (select * from ("
        "select i.id "
        "from images i "
        "left join image_tag it on it.image_id = i.id "
        "left join image_metadata im on im.image_id = i.id "

    )
    if len(where_clauses) > 0:
        sql += "where "
        previous_clause = False
        for where_clause in where_clauses:
            if previous_clause:
                sql += "and "
            sql += where_clause + " "
            previous_clause = True
    sql += (
        "limit 500) as img2) "
        "order by i2.time_created desc"
    )

    print(sql)
    print(where_params)

    try:
        response = rds_client.execute_statement(
            resourceArn = cluster_arn, 
            secretArn = secret_arn, 
            database = database, 
            sql = sql,
            parameters = where_params
        )
    except rds_client.exceptions.BadRequestException as e:
        print(e)
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'OPTIONS,GET',
            },
            'body': 'Could not connect to database'
        }

    images = {}
    for record in response['records']:
        image_id = record[0]['stringValue']
        if image_id not in images:
            images[image_id] = {
                'id': image_id,
                'timeCreated': record[1]['stringValue'],
                'tags': {},
                'metadata': {},
            }

        if 'stringValue' in record[2]:
            tag = record[2]['stringValue']
            images[image_id]['tags'][tag] = True

        if 'stringValue' in record[3] and 'stringValue' in record[4]:
            metadata_type = record[3]['stringValue']
            metadata_value = record[4]['stringValue']
            images[image_id]['metadata'][metadata_type] = metadata_value

    images_list = list(
        map(lambda image: {
            **image,
            'tags': list(image['tags'].keys())
        }, images.values())
    )

    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
        },
        'body': json.dumps({'images': images_list})
    }