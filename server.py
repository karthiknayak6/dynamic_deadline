from flask import Flask, request, jsonify, Response
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
ACCESS_TOKEN = os.getenv('ASANA_ACCESS_TOKEN')
if not ACCESS_TOKEN:
    raise ValueError("Please set ASANA_ACCESS_TOKEN in the environment variables")

HEADERS = {
    'Authorization': f'Bearer {ACCESS_TOKEN}',
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

app = Flask(__name__)
processed_events = set()  # To deduplicate events


@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    print(f"Received {request.method} request to /webhook")
    print(f"Headers: {dict(request.headers)}")

    # Handle webhook handshake for both GET and POST requests
    x_hook_secret = request.headers.get('X-Hook-Secret')
    if x_hook_secret:
        print(f"Received X-Hook-Secret: {x_hook_secret}")
        response = Response(response='', status=200)
        response.headers['X-Hook-Secret'] = x_hook_secret
        print(f"Sending handshake response: {response.headers}")
        return response

    if request.method == 'POST':
        try:
            print(f"Received webhook POST data: {request.json}")
            webhook_data = request.json
            events = webhook_data.get('events', [])
            for event in events:
                process_event(event)
            return jsonify({"status": "success"}), 200

        except Exception as e:
            print(f"Error processing webhook: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"error": "Invalid request"}), 400


def process_event(event):
    try:
        event_key = (event['created_at'], event['resource']['gid'], event['action'])
        if event_key in processed_events:
            print("Duplicate event detected, skipping:", event_key)
            return
        processed_events.add(event_key)

        task_id = event['resource']['gid']
        task_data = fetch_task_details(task_id)

        if not task_data:
            print(f"No task data found for task ID: {task_id}")
            return

        print(f"Processing event for task ID: {task_id}")

        if event['action'] == 'changed':
            if 'custom_fields' in task_data:
                handle_priority_based_due_date(task_id, task_data)

            if is_high_priority_in_progress(task_data):
                print("High-priority task moved to 'In Progress', adjusting other tasks...")
                adjust_due_dates_for_in_progress(task_id, task_data)

    except Exception as e:
        print(f"Error in process_event: {e}")


def is_high_priority_in_progress(task_data):
    try:
        custom_fields = task_data.get('custom_fields', [])
        stage_field = None
        priority_field = None

        for field in custom_fields:
            if field.get('name', '').lower() == 'stage':
                stage_field = field
            if field.get('name', '').lower() == 'priority':
                priority_field = field

        if not stage_field or not stage_field.get('enum_value'):
            print("Stage field not found or not set:", stage_field)
            return False
        if not priority_field or not priority_field.get('enum_value'):
            print("Priority field not found or not set:", priority_field)
            return False

        stage = stage_field['enum_value'].get('name', '').lower()
        priority = priority_field['enum_value'].get('name', '').lower()

        print(f"Task Stage: {stage}, Priority: {priority}")
        return stage == 'in progress' and priority == 'high'

    except Exception as e:
        print(f"Error checking stage and priority: {e}")
    return False


def adjust_due_dates_for_in_progress(excluded_task_id, task_data):
    """
    Adjusts the due dates for all tasks in 'In Progress' except the triggering high-priority task.
    """
    try:
        project_gid = task_data.get('memberships', [{}])[0].get('project', {}).get('gid')
        if not project_gid:
            return

        in_progress_tasks = get_in_progress_tasks(project_gid)
        for task in in_progress_tasks:
            task_id = task['gid']
            if task_id == excluded_task_id:
                continue

            # Fetch task details to get the current due date
            task_details = fetch_task_details(task_id)
            if not task_details:
                continue

            current_due_date = task_details.get('due_on')
            if not current_due_date:
                continue

            # Check if the due date is already updated to prevent infinite updates
            if is_due_date_updated(task_id, current_due_date):
                continue

            # Calculate the new due date (+2 days)
            new_due_date = (datetime.strptime(current_due_date, '%Y-%m-%d') + timedelta(days=2)).strftime('%Y-%m-%d')

            # Update the task with the new due date
            update_response = requests.put(
                f"https://app.asana.com/api/1.0/tasks/{task_id}",
                headers=HEADERS,
                json={"data": {"due_on": new_due_date}}
            )

            if update_response.status_code == 200:
                print(f"Updated due date for task {task_id} to {new_due_date}")
                # Mark this task as processed with its new due date
                processed_events.add((task_id, new_due_date))
            else:
                print(f"Failed to update due date for task {task_id}: {update_response.status_code} - {update_response.text}")

    except Exception as e:
        print(f"Error adjusting due dates: {e}")

def is_due_date_updated(task_id, current_due_date):
    """
    Check if the task's due date is already updated to avoid infinite updates.
    """
    # Check if the task ID and the current due date are in the processed events
    return (task_id, current_due_date) in processed_events

def handle_priority_based_due_date(task_id, task_data):
    """
    Sets a due date for the task based on its priority, but only if no due date is already assigned.
    """
    try:
        # Check if a due date already exists
        existing_due_date = task_data.get('due_on')
        if existing_due_date:
            print(f"Task {task_id} already has a due date: {existing_due_date}. Skipping priority-based due date assignment.")
            return

        custom_fields = task_data.get('custom_fields', [])
        priority_field = None
        for field in custom_fields:
            if field.get('name', '').lower() == 'priority':
                priority_field = field
                break

        if not priority_field or not priority_field.get('enum_value'):
            print(f"No priority set for task {task_id}")
            return

        priority_value = priority_field['enum_value'].get('name', '').lower()
        print(f"Setting due date based on priority: {priority_value}")

        priority_to_days = {
            'high': 2,
            'medium': 7,
            'low': 14
        }
        days_to_add = priority_to_days.get(priority_value)
        if days_to_add is None:
            print(f"Unknown priority: {priority_value}")
            return

        new_due_date = (datetime.utcnow() + timedelta(days=days_to_add)).strftime('%Y-%m-%d')

        update_response = requests.put(
            f"https://app.asana.com/api/1.0/tasks/{task_id}",
            headers=HEADERS,
            json={"data": {"due_on": new_due_date}}
        )

        if update_response.status_code == 200:
            print(f"Due date updated successfully for task {task_id} to {new_due_date}")
        else:
            print(f"Failed to update due date: {update_response.status_code} - {update_response.text}")

    except Exception as e:
        print(f"Error handling due date update: {e}")



def get_in_progress_tasks(project_gid):
    """
    Get all tasks in the project that have the 'In Progress' value in the 'Stage' custom field.
    """
    try:
        response = requests.get(
            f"https://app.asana.com/api/1.0/projects/{project_gid}/tasks",
            headers=HEADERS,
            params={'opt_fields': 'gid,name,memberships.project.gid,custom_fields'}
        )
        if response.status_code == 200:
            tasks = response.json().get('data', [])
            in_progress_tasks = []

            for task in tasks:
                custom_fields = task.get('custom_fields', [])
                # Check if 'Stage' custom field exists and if its value is 'In Progress'
                for field in custom_fields:
                    if field.get('name', '').lower() == 'stage' and field.get('enum_value'):
                        stage_value = field['enum_value'].get('name', '').lower()
                        if stage_value == 'in progress':
                            in_progress_tasks.append(task)
                            break

            return in_progress_tasks

    except Exception as e:
        print(f"Error getting in-progress tasks: {e}")
    return []


def fetch_task_details(task_id):
    """
    Fetch task details from Asana.
    """
    try:
        response = requests.get(
            f"https://app.asana.com/api/1.0/tasks/{task_id}",
            headers=HEADERS,
            params={'opt_fields': 'gid,name,custom_fields,due_on,memberships.project.gid,memberships.section.gid'}
        )
        if response.status_code == 200:
            return response.json().get('data')
    except Exception as e:
        print(f"Error fetching task details: {e}")
    return None


if __name__ == '__main__':
    print("Starting Asana automation webhook server...")
    app.run(host='0.0.0.0', port=3000, debug=True)
