import json
import math
import os

from datetime import datetime

import psycopg2


IMAGES_PER_PAGE = 100


def lambda_handler(event, context):
    if 'DB_CONN' not in os.environ:
        print("DB_CONN environment variable not set")
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'OPTIONS,GET',
            },
            'body': 'Could not connect to database'
        }

    where_clauses = []
    where_params = {}
    if event['queryStringParameters']:
        if 'start_date' in event['queryStringParameters']:
            from_datetime = datetime.strptime(event['queryStringParameters']['start_date'], "%Y-%m-%dT%H:%M:00.000Z")
            where_clauses.append('time_created >= %(from_datetime)s')
            where_params['from_datetime'] = str(from_datetime)
        if 'end_date' in event['queryStringParameters']:
            to_datetime = datetime.strptime(event['queryStringParameters']['end_date'], "%Y-%m-%dT%H:%M:00.000Z")
            where_clauses.append('time_created < %(to_datetime)s')
            where_params['to_datetime'] = str(to_datetime)
        if 'tag' in event['multiValueQueryStringParameters']:
            tag_num = 1
            for tag in event['multiValueQueryStringParameters']['tag']:
                where_clauses.append(f'tag = %(tag_{tag_num})s')
                where_params[f'tag_{tag_num}'] = tag
                tag_num += 1
        if 'photographer' in event['queryStringParameters']:
            photographer = event['queryStringParameters']['photographer']
            where_clauses.append("im.type = 'photographer' and im.value = %(photographer)s")
            where_params['photographer'] = photographer
        if 'page' in event['queryStringParameters']:
            offset = int(event['queryStringParameters']['page']) * IMAGES_PER_PAGE
        else:
            offset = 0

    sql = (
        "select i2.id, i2.time_created, it2.tag, im2.type, im2.value "
        "from images i2 "
        "left join image_tag it2 on it2.image_id = i2.id "
        "left join image_metadata im2 on im2.image_id = i2.id "
        "where i2.id in ("
        "select id from ("
        "select distinct i.id, i.time_created "
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
        "order by i.time_created "
        f"limit {IMAGES_PER_PAGE} "
        f"offset {offset}"
        ")"
        ")"
        "order by i2.time_created"
    )

    # print()
    # print(sql)
    # print()
    # print(where_params)
    # print()

    conn = psycopg2.connect(os.environ['DB_CONN'])

    with conn.cursor() as cur:
        cur.execute(sql, where_params)
        records = cur.fetchall()

    images = {}
    for record in records:
        image_id = record[0]
        if image_id not in images:
            images[image_id] = {
                'id': image_id,
                'timeCreated': str(record[1]),
                'tags': {},
                'metadata': {},
            }

        if record[2] is not None:
            tag = record[2]
            images[image_id]['tags'][tag] = True

        if record[3] is not None and record[4] is not None:
            metadata_type = record[3]
            metadata_value = record[4]
            images[image_id]['metadata'][metadata_type] = metadata_value

    images_list = list(
        map(lambda image: {
            **image,
            'tags': list(image['tags'].keys())
        }, images.values())
    )


    sql = (
        "select count(distinct i.id) "
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

    # print()
    # print(sql)
    # print()
    # print(where_params)
    # print()

    with conn.cursor() as cur:
        cur.execute(sql, where_params)
        result = cur.fetchone()
        num_images_matched = result[0]

    conn.close()

    # print(f"Num images matched: {num_images_matched}")
    # print(f"Num images returned: {len(images_list)}")
    # print()

    return {
        'statusCode': 200,
        'headers': {
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
        },
        'body': json.dumps({
            'images': images_list,
            'images_matched': num_images_matched,
            'pages': math.ceil(num_images_matched / IMAGES_PER_PAGE),
        })
    }