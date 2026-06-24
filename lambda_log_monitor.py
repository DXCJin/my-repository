import boto3
import json
import os
import re
from datetime import datetime, timezone

logs_client = boto3.client('logs')
ses_client = boto3.client('ses', region_name='ap-northeast-1')

LOG_GROUP = os.environ['LOG_GROUP_NAME']
KEYWORD = os.environ['KEYWORD']
TO_EMAIL = os.environ['TO_EMAIL']
FROM_EMAIL = os.environ['FROM_EMAIL']


def lambda_handler(event, context):
    for record in event.get('Records', [event]):
        message = record.get('Sns', {}).get('Message', '{}')
        alarm = json.loads(message)

        trigger_time = alarm.get('StateChangeTime', '')
        alarm_name = alarm.get('AlarmName', '')

        # Parse trigger time to search logs around that time
        try:
            dt = datetime.strptime(trigger_time[:19], '%Y-%m-%dT%H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc)
            end_ms = int(dt.timestamp() * 1000)
            start_ms = end_ms - (5 * 60 * 1000)  # 5 minutes before trigger
        except Exception:
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            start_ms = end_ms - (5 * 60 * 1000)

        # Search CloudWatch Logs for matching lines
        matching_lines = search_logs(start_ms, end_ms)

        if matching_lines:
            send_email(alarm_name, trigger_time, matching_lines)

    return {'statusCode': 200}


def search_logs(start_ms, end_ms):
    matching = []
    try:
        paginator = logs_client.get_paginator('filter_log_events')
        pages = paginator.paginate(
            logGroupName=LOG_GROUP,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern=f'"{KEYWORD}"'
        )
        for page in pages:
            for event in page.get('events', []):
                ts = datetime.fromtimestamp(
                    event['timestamp'] / 1000, tz=timezone.utc
                ).strftime('%Y-%m-%d %H:%M:%S UTC')
                matching.append(f"[{ts}] {event['message'].strip()}")
    except Exception as e:
        matching.append(f"(ログ取得エラー: {str(e)})")
    return matching


def send_email(alarm_name, trigger_time, lines):
    lines_text = '\n'.join(lines)
    body = f"""キーワード検知通知

アラーム名: {alarm_name}
検知時刻: {trigger_time}
キーワード: {KEYWORD}
ロググループ: {LOG_GROUP}

--- 該当ログ行 ---
{lines_text}
------------------

※ このメールは自動送信です。
"""
    ses_client.send_email(
        Source=FROM_EMAIL,
        Destination={'ToAddresses': [TO_EMAIL]},
        Message={
            'Subject': {
                'Data': f'[AWS Alert] キーワード "{KEYWORD}" を検知しました',
                'Charset': 'UTF-8'
            },
            'Body': {
                'Text': {
                    'Data': body,
                    'Charset': 'UTF-8'
                }
            }
        }
    )
