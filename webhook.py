import requests
import os
from dotenv import load_dotenv

class AsanaWebhookSetup:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        self.base_url = 'https://app.asana.com/api/1.0'

    def get_workspace_id(self):
        """Get the first workspace ID available to the user."""
        response = requests.get(
            f'{self.base_url}/workspaces',
            headers=self.headers
        )
        workspaces = response.json()['data']
        if not workspaces:
            raise Exception("No workspaces found")
        return workspaces[0]['gid']

    def get_project_id(self, workspace_id):
        """Get the first project ID in the workspace."""
        response = requests.get(
            f'{self.base_url}/projects?workspace={workspace_id}',
            headers=self.headers
        )
        projects = response.json()['data']
        if not projects:
            raise Exception("No projects found")
        return projects[0]['gid']

    def create_webhook(self, resource_id: str, target_url: str):
        """Create a webhook for the specified resource."""
        data = {
            'data': {
                'resource': resource_id,
                'target': target_url,
                'filters': [
                    {'action': 'changed', 'resource_type': 'task'},
                    {'action': 'added', 'resource_type': 'task'}
                ]
            }
        }
        response = requests.post(
            f'{self.base_url}/webhooks',
            headers=self.headers,
            json=data
        )

        if response.status_code == 201:
            print("Webhook created successfully!")
            return response.json()['data']
        else:
            print(f"Error creating webhook: {response.status_code}")
            print(response.json())
            return None

def main():
    load_dotenv()
    access_token = os.getenv('ASANA_ACCESS_TOKEN')
    if not access_token:
        raise ValueError("Please set ASANA_ACCESS_TOKEN environment variable")

    # Get the ngrok URL from user input
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        raise ValueError("Please set WEBHOOK_URL in environment variables")


    setup = AsanaWebhookSetup(access_token)

    try:
        # Get workspace and project IDs
        workspace_id = setup.get_workspace_id()
        print(f"Found workspace ID: {workspace_id}")

        project_id = setup.get_project_id(workspace_id)
        print(f"Found project ID: {project_id}")

        # Create webhook
        print(f"\nSetting up webhook for URL: {webhook_url}")
        print("Please ensure your server is running before proceeding.")
        input("Press Enter to continue...")

        webhook = setup.create_webhook(project_id, webhook_url)
        if webhook:
            print("\nWebhook setup complete!")
            print(f"Webhook ID: {webhook['gid']}")
            print(f"Monitoring resource: {webhook['resource']['gid']}")
            print(f"Target URL: {webhook['target']}")

    except Exception as e:
        print(f"Error during setup: {str(e)}")

if __name__ == "__main__":
    main()
