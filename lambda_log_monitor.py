import boto3
import json
import os
from datetime import datetime, timezone

logs_client = boto3.client('logs')
ses_client = boto3.client('ses', region_name='ap-northeast-1')

LOG_GROUP = os.environ['LOG_GROUP_NAME']
KEYWORDS = [k.strip() for k in os.environ['KEYWORDS'].split(',')]
TO_EMAIL = os.environ['TO_EMAIL']
FROM_EMAIL = os.environ['FROM_EMAIL']


def lambda_handler(event, context):
    for record in event.get('Records', []):
        message = record.get('Sns', {}).get('Message', '{}')
        alarm = json.loads(message)

        trigger_time = alarm.get('StateChangeTime', '')
        alarm_name = alarm.get('AlarmName', '')

        try:
            dt = datetime.strptime(trigger_time[:19], '%Y-%m-%dT%H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc)
            end_ms = int(dt.timestamp() * 1000)
            start_ms = end_ms - (5 * 60 * 1000)
        except Exception:
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            start_ms = end_ms - (5 * 60 * 1000)

        # Search for each keyword and collect matching lines
        all_matches = {}
        for keyword in KEYWORDS:
            lines = search_logs(start_ms, end_ms, keyword)
            if lines:
                all_matches[keyword] = lines

        if all_matches:
            send_email(alarm_name, trigger_time, all_matches)

    return {'statusCode': 200}


def search_logs(start_ms, end_ms, keyword):
    matching = []
    try:
        paginator = logs_client.get_paginator('filter_log_events')
        pages = paginator.paginate(
            logGroupName=LOG_GROUP,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern=f'"{keyword}"'
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


def send_email(alarm_name, trigger_time, all_matches):
    sections = []
    for keyword, lines in all_matches.items():
        section = f"キーワード: {keyword}\n" + '\n'.join(lines)
        sections.append(section)

    body = f"""キーワード検知通知

アラーム名: {alarm_name}
検知時刻: {trigger_time}
監視キーワード: {', '.join(KEYWORDS)}
ロググループ: {LOG_GROUP}

{'=' * 40}
{chr(10).join(sections)}
{'=' * 40}

※ このメールは自動送信です。
"""
    ses_client.send_email(
        Source=FROM_EMAIL,
        Destination={'ToAddresses': [TO_EMAIL]},
        Message={
            'Subject': {
                'Data': f'[AWS Alert] キーワードを検知しました: {", ".join(all_matches.keys())}',
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
