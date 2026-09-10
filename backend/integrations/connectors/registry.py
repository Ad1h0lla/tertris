import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


CONNECTOR_CATALOG = {'gmail': {'name': 'Gmail',
           'category': 'communication',
           'description': 'Send emails, read inbox, manage labels',
           'credentials_needed': ['GMAIL_API_KEY'],
           'actions': ['send_email', 'read_emails', 'create_draft', 'add_label'],
           'free_tier': True,
           'setup_url': 'https://console.cloud.google.com/apis/library/gmail.googleapis.com'},
 'slack': {'name': 'Slack',
           'category': 'communication',
           'description': 'Send messages, create channels, post to workspaces',
           'credentials_needed': ['SLACK_BOT_TOKEN'],
           'actions': ['send_message', 'create_channel', 'post_to_channel', 'upload_file'],
           'free_tier': True,
           'setup_url': 'https://api.slack.com/apps'},
 'discord': {'name': 'Discord',
             'category': 'communication',
             'description': 'Post to channels, send DMs, manage servers',
             'credentials_needed': ['DISCORD_BOT_TOKEN'],
             'actions': ['send_message', 'post_to_channel', 'create_thread', 'send_dm'],
             'free_tier': True,
             'setup_url': 'https://discord.com/developers/applications'},
 'telegram': {'name': 'Telegram',
              'category': 'communication',
              'description': 'Send messages, post to channels, manage bots',
              'credentials_needed': ['TELEGRAM_BOT_TOKEN'],
              'actions': ['send_message', 'post_to_channel', 'send_document'],
              'free_tier': True,
              'setup_url': 'https://t.me/BotFather'},
 'whatsapp': {'name': 'WhatsApp Business',
              'category': 'communication',
              'description': 'Send WhatsApp messages via Business API',
              'credentials_needed': ['WHATSAPP_API_KEY', 'WHATSAPP_PHONE_ID'],
              'actions': ['send_message', 'send_template'],
              'free_tier': False,
              'setup_url': 'https://developers.facebook.com/docs/whatsapp'},
 'twilio': {'name': 'Twilio',
            'category': 'communication',
            'description': 'Send SMS, make calls, WhatsApp messages',
            'credentials_needed': ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'],
            'actions': ['send_sms', 'make_call', 'send_whatsapp'],
            'free_tier': True,
            'setup_url': 'https://www.twilio.com/console'},
 'google_sheets': {'name': 'Google Sheets',
                   'category': 'productivity',
                   'description': 'Read and write spreadsheet data',
                   'credentials_needed': ['GOOGLE_SHEETS_API_KEY', 'GOOGLE_SHEETS_SPREADSHEET_ID'],
                   'actions': ['read_rows', 'append_row', 'update_row', 'create_sheet'],
                   'free_tier': True,
                   'setup_url': 'https://console.cloud.google.com/apis/library/sheets.googleapis.com'},
 'google_drive': {'name': 'Google Drive',
                  'category': 'productivity',
                  'description': 'Upload, download, organize files',
                  'credentials_needed': ['GOOGLE_DRIVE_API_KEY'],
                  'actions': ['upload_file', 'download_file', 'create_folder', 'list_files'],
                  'free_tier': True,
                  'setup_url': 'https://console.cloud.google.com/apis/library/drive.googleapis.com'},
 'google_calendar': {'name': 'Google Calendar',
                     'category': 'productivity',
                     'description': 'Create events, check availability, manage calendars',
                     'credentials_needed': ['GOOGLE_CALENDAR_API_KEY'],
                     'actions': ['create_event', 'list_events', 'update_event', 'delete_event'],
                     'free_tier': True,
                     'setup_url': 'https://console.cloud.google.com/apis/library/calendar.googleapis.com'},
 'notion': {'name': 'Notion',
            'category': 'productivity',
            'description': 'Create pages, update databases, manage workspace',
            'credentials_needed': ['NOTION_API_KEY'],
            'actions': ['create_page', 'update_page', 'query_database', 'append_block'],
            'free_tier': True,
            'setup_url': 'https://www.notion.so/my-integrations'},
 'airtable': {'name': 'Airtable',
              'category': 'productivity',
              'description': 'Read and write structured database records',
              'credentials_needed': ['AIRTABLE_API_KEY', 'AIRTABLE_BASE_ID'],
              'actions': ['list_records', 'create_record', 'update_record', 'delete_record'],
              'free_tier': True,
              'setup_url': 'https://airtable.com/account'},
 'github': {'name': 'GitHub',
            'category': 'development',
            'description': 'Create repos, manage issues, push code',
            'credentials_needed': ['GITHUB_TOKEN'],
            'actions': ['create_repo', 'create_issue', 'create_pr', 'push_file', 'list_repos'],
            'free_tier': True,
            'setup_url': 'https://github.com/settings/tokens'},
 'linear': {'name': 'Linear',
            'category': 'project_management',
            'description': 'Create issues, manage projects, track progress',
            'credentials_needed': ['LINEAR_API_KEY'],
            'actions': ['create_issue', 'update_issue', 'list_issues', 'create_project'],
            'free_tier': True,
            'setup_url': 'https://linear.app/settings/api'},
 'jira': {'name': 'Jira',
          'category': 'project_management',
          'description': 'Create tickets, manage sprints, track bugs',
          'credentials_needed': ['JIRA_API_KEY', 'JIRA_DOMAIN', 'JIRA_EMAIL'],
          'actions': ['create_issue', 'update_issue', 'list_issues', 'add_comment'],
          'free_tier': True,
          'setup_url': 'https://id.atlassian.com/manage-profile/security/api-tokens'},
 'asana': {'name': 'Asana',
           'category': 'project_management',
           'description': 'Create tasks, manage projects, assign work',
           'credentials_needed': ['ASANA_ACCESS_TOKEN'],
           'actions': ['create_task', 'update_task', 'list_tasks', 'create_project'],
           'free_tier': True,
           'setup_url': 'https://app.asana.com/0/developer-console'},
 'trello': {'name': 'Trello',
            'category': 'project_management',
            'description': 'Create cards, manage boards, move tasks',
            'credentials_needed': ['TRELLO_API_KEY', 'TRELLO_TOKEN'],
            'actions': ['create_card', 'update_card', 'move_card', 'create_list'],
            'free_tier': True,
            'setup_url': 'https://trello.com/app-key'},
 'stripe': {'name': 'Stripe',
            'category': 'payments',
            'description': 'Create products, process payments, manage subscriptions',
            'credentials_needed': ['STRIPE_SECRET_KEY'],
            'actions': ['create_product', 'create_price', 'create_customer', 'create_invoice'],
            'free_tier': True,
            'setup_url': 'https://dashboard.stripe.com/apikeys'},
 'lemonsqueezy': {'name': 'LemonSqueezy',
                  'category': 'payments',
                  'description': 'Sell digital products, manage subscriptions',
                  'credentials_needed': ['LEMONSQUEEZY_API_KEY'],
                  'actions': ['create_product', 'list_orders', 'create_discount'],
                  'free_tier': True,
                  'setup_url': 'https://app.lemonsqueezy.com/settings/api'},
 'sendgrid': {'name': 'SendGrid',
              'category': 'email_marketing',
              'description': 'Send transactional emails, manage contacts, sequences',
              'credentials_needed': ['SENDGRID_API_KEY'],
              'actions': ['send_email', 'add_contact', 'create_list', 'send_campaign'],
              'free_tier': True,
              'setup_url': 'https://app.sendgrid.com/settings/api_keys'},
 'mailchimp': {'name': 'Mailchimp',
               'category': 'email_marketing',
               'description': 'Manage email lists, send campaigns, track opens',
               'credentials_needed': ['MAILCHIMP_API_KEY', 'MAILCHIMP_SERVER'],
               'actions': ['add_subscriber', 'send_campaign', 'create_list', 'get_stats'],
               'free_tier': True,
               'setup_url': 'https://mailchimp.com/account/api/'},
 'resend': {'name': 'Resend',
            'category': 'email_marketing',
            'description': 'Developer-friendly email sending API',
            'credentials_needed': ['RESEND_API_KEY'],
            'actions': ['send_email', 'create_audience', 'add_contact'],
            'free_tier': True,
            'setup_url': 'https://resend.com/api-keys'},
 'twitter': {'name': 'Twitter/X',
             'category': 'social_media',
             'description': 'Post tweets, search mentions, manage account',
             'credentials_needed': ['TWITTER_API_KEY', 'TWITTER_API_SECRET', 'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_SECRET'],
             'actions': ['post_tweet', 'search_tweets', 'get_mentions', 'follow_user'],
             'free_tier': False,
             'setup_url': 'https://developer.twitter.com/en/portal/dashboard'},
 'reddit': {'name': 'Reddit',
            'category': 'social_media',
            'description': 'Post to subreddits, monitor mentions, search',
            'credentials_needed': ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET', 'REDDIT_USERNAME', 'REDDIT_PASSWORD'],
            'actions': ['post_to_subreddit', 'search_posts', 'get_comments', 'reply_to_post'],
            'free_tier': True,
            'setup_url': 'https://www.reddit.com/prefs/apps'},
 'linkedin': {'name': 'LinkedIn',
              'category': 'social_media',
              'description': 'Post updates, manage company page, search',
              'credentials_needed': ['LINKEDIN_ACCESS_TOKEN'],
              'actions': ['create_post', 'get_profile', 'search_companies'],
              'free_tier': True,
              'setup_url': 'https://www.linkedin.com/developers/apps'},
 'google_analytics': {'name': 'Google Analytics',
                      'category': 'analytics',
                      'description': 'Track website traffic, user behavior, conversions',
                      'credentials_needed': ['GA_MEASUREMENT_ID', 'GA_API_SECRET'],
                      'actions': ['track_event', 'get_report', 'get_realtime_users'],
                      'free_tier': True,
                      'setup_url': 'https://analytics.google.com'},
 'mixpanel': {'name': 'Mixpanel',
              'category': 'analytics',
              'description': 'Track user events, funnels, retention',
              'credentials_needed': ['MIXPANEL_TOKEN'],
              'actions': ['track_event', 'identify_user', 'get_funnel'],
              'free_tier': True,
              'setup_url': 'https://mixpanel.com/settings/project'},
 'hubspot': {'name': 'HubSpot',
             'category': 'crm',
             'description': 'Manage contacts, deals, companies, pipelines',
             'credentials_needed': ['HUBSPOT_API_KEY'],
             'actions': ['create_contact', 'create_deal', 'update_contact', 'add_note', 'list_contacts'],
             'free_tier': True,
             'setup_url': 'https://app.hubspot.com/account-and-billing/account/api-key'},
 'salesforce': {'name': 'Salesforce',
                'category': 'crm',
                'description': 'Manage leads, opportunities, accounts',
                'credentials_needed': ['SALESFORCE_ACCESS_TOKEN', 'SALESFORCE_INSTANCE_URL'],
                'actions': ['create_lead', 'update_opportunity', 'create_contact', 'run_soql'],
                'free_tier': False,
                'setup_url': 'https://developer.salesforce.com'},
 'postgresql': {'name': 'PostgreSQL',
                'category': 'database',
                'description': 'Query and write to PostgreSQL databases',
                'credentials_needed': ['POSTGRES_URL'],
                'actions': ['run_query', 'insert_row', 'update_row', 'create_table'],
                'free_tier': True,
                'setup_url': 'Your PostgreSQL connection string'},
 'mysql': {'name': 'MySQL',
           'category': 'database',
           'description': 'Query and write to MySQL databases',
           'credentials_needed': ['MYSQL_HOST', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DB'],
           'actions': ['run_query', 'insert_row', 'update_row'],
           'free_tier': True,
           'setup_url': 'Your MySQL credentials'},
 'supabase': {'name': 'Supabase',
              'category': 'database',
              'description': 'Postgres database with REST API, auth, storage',
              'credentials_needed': ['SUPABASE_URL', 'SUPABASE_KEY'],
              'actions': ['insert_row', 'select_rows', 'update_row', 'delete_row', 'upload_file'],
              'free_tier': True,
              'setup_url': 'https://app.supabase.com/project/_/settings/api'},
 'mongodb': {'name': 'MongoDB',
             'category': 'database',
             'description': 'Read and write MongoDB collections',
             'credentials_needed': ['MONGODB_URI'],
             'actions': ['find', 'insert', 'update', 'delete', 'aggregate'],
             'free_tier': True,
             'setup_url': 'https://cloud.mongodb.com'},
 'vercel': {'name': 'Vercel',
            'category': 'deployment',
            'description': 'Deploy websites and apps instantly',
            'credentials_needed': ['VERCEL_TOKEN'],
            'actions': ['deploy', 'list_deployments', 'get_deployment_url', 'rollback'],
            'free_tier': True,
            'setup_url': 'https://vercel.com/account/tokens'},
 'railway': {'name': 'Railway',
             'category': 'deployment',
             'description': 'Deploy apps and databases to the cloud',
             'credentials_needed': ['RAILWAY_TOKEN'],
             'actions': ['deploy', 'list_services', 'get_logs'],
             'free_tier': True,
             'setup_url': 'https://railway.app/account/tokens'},
 'netlify': {'name': 'Netlify',
             'category': 'deployment',
             'description': 'Deploy static sites and serverless functions',
             'credentials_needed': ['NETLIFY_TOKEN'],
             'actions': ['deploy', 'list_sites', 'get_site_url'],
             'free_tier': True,
             'setup_url': 'https://app.netlify.com/user/applications'},
 'zoom': {'name': 'Zoom',
          'category': 'meetings',
          'description': 'Get meeting transcripts, recordings, participants',
          'credentials_needed': ['ZOOM_API_KEY', 'ZOOM_API_SECRET'],
          'actions': ['get_transcript', 'list_meetings', 'get_recording'],
          'free_tier': True,
          'setup_url': 'https://marketplace.zoom.us/develop/create'},
 'fireflies': {'name': 'Fireflies.ai',
               'category': 'meetings',
               'description': 'Auto-transcribe meetings from any platform',
               'credentials_needed': ['FIREFLIES_API_KEY'],
               'actions': ['get_transcript', 'list_transcripts', 'search_transcripts'],
               'free_tier': True,
               'setup_url': 'https://app.fireflies.ai/integrations/api'},
 'aws_s3': {'name': 'AWS S3',
            'category': 'storage',
            'description': 'Upload, download, manage files in S3 buckets',
            'credentials_needed': ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_BUCKET'],
            'actions': ['upload_file', 'download_file', 'list_files', 'delete_file'],
            'free_tier': True,
            'setup_url': 'https://console.aws.amazon.com/iam'},
 'dropbox': {'name': 'Dropbox',
             'category': 'storage',
             'description': 'Upload and manage files in Dropbox',
             'credentials_needed': ['DROPBOX_ACCESS_TOKEN'],
             'actions': ['upload_file', 'download_file', 'list_folder', 'share_link'],
             'free_tier': True,
             'setup_url': 'https://www.dropbox.com/developers/apps'},
 'serper': {'name': 'Serper (Google Search)',
            'category': 'seo_marketing',
            'description': 'Search Google, get SERP data, monitor rankings',
            'credentials_needed': ['SERPER_API_KEY'],
            'actions': ['search', 'get_serp', 'image_search', 'news_search'],
            'free_tier': True,
            'setup_url': 'https://serper.dev/api-key'},
 'ahrefs': {'name': 'Ahrefs',
            'category': 'seo_marketing',
            'description': 'SEO data, backlinks, keyword research',
            'credentials_needed': ['AHREFS_API_KEY'],
            'actions': ['get_backlinks', 'keyword_research', 'site_audit'],
            'free_tier': False,
            'setup_url': 'https://ahrefs.com/api'},
 'product_hunt': {'name': 'Product Hunt',
                  'category': 'seo_marketing',
                  'description': 'Submit products, track upvotes, monitor launches',
                  'credentials_needed': ['PRODUCT_HUNT_API_KEY'],
                  'actions': ['submit_product', 'get_product', 'list_posts'],
                  'free_tier': True,
                  'setup_url': 'https://www.producthunt.com/v2/oauth/applications'},
 'webhook': {'name': 'Custom Webhook',
             'category': 'universal',
             'description': 'Connect any tool that accepts HTTP requests',
             'credentials_needed': ['WEBHOOK_URL'],
             'actions': ['post_data', 'get_data'],
             'free_tier': True,
             'setup_url': 'Your custom webhook URL'},
 'http_request': {'name': 'HTTP Request',
                  'category': 'universal',
                  'description': 'Call any REST API with any method',
                  'credentials_needed': ['API_URL', 'API_KEY'],
                  'actions': ['get', 'post', 'put', 'delete', 'patch'],
                  'free_tier': True,
                  'setup_url': 'Any REST API endpoint'}}


def get_all_connectors() -> dict:
    return CONNECTOR_CATALOG


def get_connectors_by_category() -> dict:
    categories = {}

    for key, connector in CONNECTOR_CATALOG.items():
        cat = connector.get("category", "other")

        if cat not in categories:
            categories[cat] = []

        categories[cat].append({
            "id": key,
            **connector
        })

    return categories


def get_connector(connector_id: str) -> dict:
    return CONNECTOR_CATALOG.get(connector_id)


def get_free_connectors() -> list:
    return [
        {
            "id": k,
            **v
        }
        for k, v in CONNECTOR_CATALOG.items()
        if v.get("free_tier")
    ]


def check_credentials_for_connector(connector_id: str) -> dict:
    connector = CONNECTOR_CATALOG.get(connector_id)

    if not connector:
        return {
            "error": f"Connector {connector_id} not found"
        }

    required = connector.get("credentials_needed", [])

    configured = []
    missing = []

    for cred in required:
        if os.getenv(cred):
            configured.append(cred)
        else:
            missing.append(cred)

    return {
        "connector_id": connector_id,
        "connector_name": connector.get("name", connector_id),
        "configured": configured,
        "missing": missing,
        "ready": len(missing) == 0,
        "setup_url": connector.get("setup_url", "")
    }


def get_user_ready_connectors() -> list:
    ready = []

    for connector_id in CONNECTOR_CATALOG:
        status = check_credentials_for_connector(connector_id)

        if not status.get("ready"):
            continue

        connector = CONNECTOR_CATALOG[connector_id]

        ready.append({
            "id": connector_id,
            "name": connector.get("name", connector_id),
            "category": connector.get("category"),
            "actions": connector.get("actions", [])
        })

    return ready
