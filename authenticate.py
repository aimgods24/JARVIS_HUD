import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/gmail.readonly'
]

def generate_local_token():
    # Launches browser for one-time manual approval
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES
    )
    creds = flow.run_local_server(port=0)
    
    # Save token locally for E.V.A.S. to reuse automatically
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())
    print("SUCCESS: Google authentication saved to token.json!")

if __name__ == '__main__':
    generate_local_token()