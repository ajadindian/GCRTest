import os
import json
import shutil
import logging
import time
import requests
from dotenv import load_dotenv

def get_env_variable(var_name, is_required=True):
    value = os.getenv(var_name)
    if not value and is_required:
        logging.error(f"Environment variable '{var_name}' is missing or not defined!")
        raise EnvironmentError(f"Missing required environment variable: {var_name}")
    return value

def check_azure_subscription(api_key, azure_endpoint, api_version):
    logging.info("Checking Azure subscription availability...")

    try:
        # Use a valid OpenAI API endpoint to verify the subscription
        url = f"{azure_endpoint}/openai/models?api-version={api_version}"
        headers = {
            'api-key': api_key,
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers)

        # Check if the subscription check was successful
        if response.status_code == 200:
            logging.info("Azure subscription is active and available.")
            return True
        else:
            logging.error(f"Failed to verify Azure subscription: {response.status_code} - {response.reason}")
            return False

    except requests.RequestException as e:
        logging.error(f"An error occurred while checking Azure subscription: {e}")
        return False

def handle_remove_error(func, path, exc_info):
    """Custom error handler for shutil.rmtree."""
    logging.error(f"Error removing {path}: {exc_info[1]}")

def remove_directory(directory):
    """Remove a directory and handle errors."""
    if os.path.exists(directory):
        try:
            shutil.rmtree(directory, onerror=handle_remove_error)
            logging.info(f"Directory '{directory}' deleted successfully!")
        except Exception as e:
            logging.error(f"An unexpected error occurred while removing directory '{directory}': {e}")
    else:
        logging.warning(f"Directory '{directory}' does not exist, skipping deletion.")

def _handle_remove_error(func, path, exc_info):
    """
    Custom error handler for shutil.rmtree.
    Logs the error and continues with the removal process.
    """
    if func in (os.unlink, os.remove):
        logging.warning(f"Failed to remove file '{path}': {exc_info[1]}")
    elif func in (os.rmdir, os.removedirs):
        logging.warning(f"Failed to remove directory '{path}': {exc_info[1]}")
    else:
        logging.error(f"Unexpected error while removing '{path}': {exc_info[1]}")

# def remove_directory(directory):
#     if os.path.exists(directory):
#         shutil.rmtree(directory)
#         logging.info(f"Directory '{directory}' deleted successfully!")

# def ensure_directory_structure(path):
#     if not os.path.exists(path):
#         os.makedirs(path)
#         logging.info(f"Folder '{path}' created.")

def ensure_directory_structure(path):
    """Ensure that the directory structure exists."""
    try:
        if os.path.exists(path):
            if os.path.isdir(path):
                logging.info(f"Directory '{path}' already exists. Skipping creation.")
            else:
                logging.warning(f"'{path}' exists but is not a directory. Attempting to remove and recreate.")
                os.remove(path)
                os.makedirs(path)
                logging.info(f"Directory '{path}' created successfully after removing the conflicting file.")
        else:
            os.makedirs(path)
            logging.info(f"Directory '{path}' created successfully.")
    except FileExistsError:
        logging.warning(f"Directory '{path}' already exists. This error was safely handled.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while ensuring directory '{path}': {e}")


def identify_source_files(directory, extensions, excluded_files):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file in excluded_files:
                continue
            if file.endswith(tuple(extensions)):
                yield os.path.join(root, file)

def load_prompts_from_env():
    prompts = []
    for key in os.environ:
        if key.startswith("PROMPT_"):
            # Split the prompt and its flag
            prompt_data = os.getenv(key).split(", ")
            if len(prompt_data) == 2 and prompt_data[1].lower() == "y":
                prompts.append(prompt_data[0])
            else:
                logging.warning(f"Skipping prompt '{key}' as per .env configuration.")
    return prompts

def create_unit_test_files(client, assistant, file_list, test_file_directory):
    prompt_testcase = get_env_variable('PROMPT_GENERATE_TESTCASES', is_required=False)
    if prompt_testcase:
        if ", " in prompt_testcase:
            prompt, toggle = prompt_testcase.rsplit(", ", 1)
            toggle = toggle.strip().lower()
        else:
            logging.warning("PROMPT_GENERATE_TESTCASES format is incorrect in .env.")
            return
    else:
        logging.warning("Unit test case prompt not found in .env.")
        return
    if toggle != 'y':
        logging.info("Skipping unit test generation as per .env configuration.")
        return
    for file_path in file_list:
        file_name = os.path.basename(file_path)
        base_name, ext = os.path.splitext(file_name)
        if 'test' in base_name.lower():
            logging.info(f"Skipping test file: {file_path}")
            continue
        test_file_name = f"{base_name}Test{ext}"
        test_file_path = os.path.join(test_file_directory, test_file_name)
        if os.path.exists(test_file_path):
            logging.info(f"Test file already exists: {test_file_path}")
            continue
        prompt_formatted = prompt.format(file_extension=ext, file_name=file_name)
        with open(file_path, "rb") as file:
            try:
                uploaded_file = client.files.create(file=file, purpose='assistants')
                logging.info(f"File uploaded for unit test creation: {file_name}")
            except Exception as e:
                logging.error(f"Error uploading file {file_name} for unit test: {e}")
                continue

        logging.info(f"Creating unit test file for: {file_name}")
        thread = client.beta.threads.create(
            messages=[{"role": "user", "content": prompt_formatted, "file_ids": [uploaded_file.id]}]
        )
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant.id)
        
        start_time = time.time()
        while True:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id).status
            # logging.info(f"Unit test creation status for {file_name}: {run_status}")
            if run_status == 'completed':
                break
            elif time.time() - start_time > 1200:
                logging.warning(f"Unit test creation timed out for file: {file_name}")
                break
            else:
                time.sleep(5)

        # Handle the retrieved data for the test case creation...
        logging.info(f"Unit test file creation completed for {file_name}")

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        data = json.loads(messages.model_dump_json(indent=2))
        code = None
        if data['data'] and data['data'][0]['content'] and data['data'][0]['content'][0]['text']['annotations']:
            code = data['data'][0]['content'][0]['text']['annotations'][0]['file_path']['file_id']
        if code:
            try:
                content = client.files.content(code)
                content.write_to_file(test_file_path)
                logging.info(f"Unit test file created: {test_file_path}")
            except Exception as e:
                logging.error(f"Failed to write unit test file {test_file_path}: {e}")
        else:
            logging.error(f"Failed to create unit test for file: {file_path}")

def apply_green_prompts(client, assistant, file_id, prompt, refined_file_path):
    logging.info(f"Applying prompt: {prompt} to file {file_id}")
    try:
        thread = client.beta.threads.create(
            messages=[{"role": "user", "content": prompt, "file_ids": [file_id]}]
        )
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant.id)

        start_time = time.time()
        while True:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id).status
            # logging.info(f"Processing status for file {file_id}: {run_status}")
            if run_status == 'completed':
                break
            elif time.time() - start_time > 1200:
                logging.warning(f"Processing timed out for file: {file_id}")
                return False
            else:
                time.sleep(5)

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        data = json.loads(messages.model_dump_json(indent=2))

        # Log the entire API response for debugging
        # logging.info(f"API response for file {file_id}: {json.dumps(data, indent=2)}")

        code = None
        if data['data'] and data['data'][0]['content'] and data['data'][0]['content'][0]['text']['annotations']:
            code = data['data'][0]['content'][0]['text']['annotations'][0]['file_path']['file_id']

        if code:
            try:
                content = client.files.content(code)
                content.write_to_file(refined_file_path)
                logging.info(f"File refined successfully with prompt: {prompt}")
                return True
            except Exception as e:
                logging.error(f"Error writing refined file for prompt {prompt}: {e}")
                return False
        else:
            logging.error(f"No code found or annotations list is empty for prompt: {prompt} and file {file_id}. Possible file-specific issue or API response problem.")
            return False

    except Exception as e:
        logging.error(f"Exception occurred while applying prompt '{prompt}' to file {file_id}: {e}")
        return False
