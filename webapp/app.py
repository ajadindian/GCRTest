from flask import Flask, render_template, request, redirect, url_for, Response, stream_with_context, send_from_directory, jsonify, send_file, abort
from dotenv import set_key, load_dotenv
from flask_socketio import SocketIO, emit
import os
import subprocess
import threading
import time
import re
from flask import render_template
import queue


app = Flask(__name__)
socketio = SocketIO(app)
process_running = False
lock = threading.Lock()

BASE_DIR = '/app/project'
# Load environment variables
env_path = '/app/.env'
load_dotenv(dotenv_path=env_path, verbose=True, override=True)

# Helper function to format paths for Windows
def format_path(path):
    return path.replace("/", "\\").replace("\\", "\\")

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/configure')
def configuration():
    return render_template('configuration.html')

@app.route('/save', methods=['POST'])
def save_config():
    try:
        azure_model = request.form.get('azure_model', 'GPT4o')
        project_path = request.form.get('project_path').strip()

        # Save to .env
        set_key(env_path, "AZURE_MODEL", azure_model)
        set_key(env_path, "PROJECT_PATH", project_path)
        print("PROJECT_PATH saved to .env:", project_path)
        
        # Remove quotes from PROJECT_PATH
        with open(env_path, 'r') as f:
            lines = f.readlines()
        
        with open(env_path, 'w') as f:
            for line in lines:
                if line.startswith("PROJECT_PATH"):
                    line = line.replace("'", "")
                f.write(line)

        # Common suffix for all prompts
        common_suffix = "and make sure the code output should keep same as it is giving and do not remove any part of code only focus on the main focus that mentioned initially"
        
        # Predefined prompts with their base text
        base_prompts = {
            "PROMPT_1": "Make the code more energy efficient",
            "PROMPT_2": "Eliminate any redundant or dead code",
            "PROMPT_3": "Simplify complex algorithms to reduce computational load",
            "PROMPT_4": "Optimize memory usage in the code",
            "PROMPT_5": "Reduce the number of dependencies",
            "PROMPT_6": "Refactor the code to reduce complexity",
            "PROMPT_7": "Test the code for edge cases"
        }

        # Process and save prompts
        for prompt_key, base_text in base_prompts.items():
            prompt_enabled = request.form.get(prompt_key.lower(), 'n')
            if prompt_enabled == 'y':
                full_prompt = f"{base_text} {common_suffix}"
                set_key(env_path, prompt_key, f"{full_prompt}, {prompt_enabled}")
            else:
                set_key(env_path, prompt_key, f"{base_text}, {prompt_enabled}")

        # Handle custom prompt (Prompt 8)
        custom_prompt_enabled = request.form.get('prompt_8', 'n')
        if custom_prompt_enabled == 'y':
            custom_prompt_text = request.form.get('prompt_8_text', '').strip()
            if custom_prompt_text:
                full_custom_prompt = f"{custom_prompt_text} {common_suffix}"
                set_key(env_path, "PROMPT_8", f"{full_custom_prompt}, {custom_prompt_enabled}")
        else:
            set_key(env_path, "PROMPT_8", f"Custom prompt, {custom_prompt_enabled}")

        # Save test cases configuration
        test_cases_enabled = request.form.get('prompt_generate_testcases', 'n')
        set_key(env_path, "PROMPT_GENERATE_TESTCASES", f"Generate test cases, {test_cases_enabled}")

        return redirect(url_for('index'))
    
    except Exception as e:
        print("Error in save_config:", str(e))
        return "Error saving configuration. Please check server logs.", 500

@app.route('/run', methods=['POST'])
def run_code_refiner():
    global process_running
    with lock:
        if process_running:
            return "Error: Process is already running.", 400  # Prevent concurrent runs

        # Signal the entrypoint script to start running
        with open('/app/run_scripts.flag', 'w') as f:
            f.write('run')

        process_running = True

    # Reload environment variables to reflect any changes made in /save
    load_dotenv(dotenv_path=env_path, override=True)

    # Fetch the project path from the .env file
    project_path = os.getenv("PROJECT_PATH", "")
    print("Project path:", project_path)  # Debugging to check if it's fetched correctly

    # Construct the URL for the emissions_report.html
    if project_path:
        report_path = os.path.join(project_path, "Report", "emissions_report.html")
        # Format the report path for URL (escape spaces and special characters)
        report_url = "file:///" + report_path.replace(" ", "%20").replace("\\", "/")
    else:
        report_url = None

    # Pass the report URL to the running.html page
    return render_template("running.html", report_url=report_url)

# @app.route('/stream')
# def stream():
#     output_queue = queue.Queue()

#     def enqueue_output(process):
#         for line in iter(process.stdout.readline, ''):
#             output_queue.put(line.strip())
#         process.stdout.close()

#     def generate():
#         with subprocess.Popen(
#             ["/bin/bash", "/app/entrypoint.sh"],
#             stdout=subprocess.PIPE,
#             stderr=subprocess.STDOUT,
#             text=True,
#             bufsize=1
#         ) as process:
#             # Start thread to read output
#             t = threading.Thread(target=enqueue_output, args=(process,))
#             t.daemon = True
#             t.start()

#             while True:
#                 try:
#                     line = output_queue.get(timeout=0.1)
#                     yield f"data: {line}\n\n"
#                 except queue.Empty:
#                     if process.poll() is not None:
#                         break

#     return Response(generate(), mimetype='text/event-stream')
@app.route('/stream')
def stream():
    """
    Stream the logs of the entrypoint script execution.
    """
    def generate():
        with subprocess.Popen(
            ["/bin/bash", "/app/entrypoint.sh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        ) as process:
            try:
                for line in iter(process.stdout.readline, ''):
                    yield f"data: {line}\n\n"
            finally:
                process.stdout.close()
                process.wait()


    return Response(generate(), mimetype='text/event-stream')

# @app.route('/stream')
# def stream():
#     def generate():
#         with subprocess.Popen(
#             ["/bin/bash", "/app/entrypoint.sh"],
#             stdout=subprocess.PIPE,
#             stderr=subprocess.STDOUT,
#             text=True,
#             bufsize=0,  # Unbuffered mode
#             universal_newlines=True
#         ) as process:
#             # Use select to non-blockingly read output
#             import select
            
#             while True:
#                 reads = [process.stdout.fileno()]
#                 ret = select.select(reads, [], [])

#                 if process.stdout in ret[0]:
#                     line = process.stdout.readline()
#                     if line == '' and process.poll() is not None:
#                         break
#                     if line:
#                         # Strip newline and send clean data
#                         yield f"data: {line.strip()}\n\n"
                
#                 if process.poll() is not None:
#                     break

#     return Response(generate(), mimetype='text/event-stream', direct_passthrough=True)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
