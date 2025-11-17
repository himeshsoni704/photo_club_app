import os
import pandas as pd
from flask import Flask, render_template_string, request, redirect, url_for

# --- Configuration ---
app = Flask(__name__)
# NOTE: When deployed on a server, writing to a local file like 'events.xlsx' 
# may not be persistent across restarts or scale well. For a production app, 
# you would switch to a database (like PostgreSQL or Firestore). 
# However, for a small club's internal use, this Excel method is acceptable.
EXCEL_FILE = 'events.xlsx' 
ADMIN_PASSKEY = 'photoadmin' # Set a strong admin passkey

INITIAL_DATA = {
    'ID': [1, 2, 3, 4, 5, 6],
    'Event Name': ['Welcome BBQ', 'City Landscape Workshop', 'Portrait Shoot Day', 'Night Sky Photography', 'Exhibition Setup', 'Club Meeting'],
    'Date': ['2025-12-01', '2025-12-05', '2025-12-10', '2025-12-15', '2025-12-18', '2025-12-20'],
    'Time Slot': ['18:00 - 20:00', '14:00 - 17:00', '09:00 - 12:00', '21:00 - 00:00', '10:00 - 16:00', '19:00 - 20:30'],
    'Status': ['Open', 'Open', 'Open', 'Open', 'Open', 'Open'],
    'Covering Member': ['None', 'None', 'None', 'None', 'None', 'None']
}

# --- Utility Functions for Excel Handling ---

def load_data():
    """Loads event data from Excel. Creates initial data if file does not exist."""
    try:
        # Load the spreadsheet
        # On some hosting platforms, the file might not be writable after creation,
        # leading to an immediate 'events.xlsx' file-not-found error on subsequent loads.
        # This implementation assumes the environment allows file writing.
        df = pd.read_excel(EXCEL_FILE)
        # Ensure the 'ID' is the index for easy referencing
        df = df.set_index('ID', drop=False)
        return df
    except FileNotFoundError:
        # Create initial data if the file is missing
        print(f"Creating new file: {EXCEL_FILE}")
        df = pd.DataFrame(INITIAL_DATA)
        df = df.set_index('ID', drop=False)
        save_data(df)
        return df
    except Exception as e:
        print(f"Error loading Excel file: {e}")
        # Return initial data frame on structural error
        return pd.DataFrame(INITIAL_DATA).set_index('ID', drop=False)


def save_data(df):
    """Saves the DataFrame back to the Excel file."""
    try:
        # Use openpyxl engine for stability
        df.to_excel(EXCEL_FILE, index=False, engine='openpyxl')
    except Exception as e:
        print(f"Error saving Excel file: {e}")
        # This is critical, we should not proceed if we can't save
        # In a real app, this would require better error logging and user notification.

# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Displays the public event schedule and handles admin login/view switch."""
    df = load_data()
    
    # 1. Admin Authentication Check
    is_admin = False
    admin_key = request.args.get('passkey')
    
    # Check if the passkey provided in the query string is correct
    if admin_key == ADMIN_PASSKEY:
        is_admin = True
    
    # Handle POST request for admin login (from the modal form)
    if request.method == 'POST' and 'admin_passkey' in request.form:
        if request.form['admin_passkey'] == ADMIN_PASSKEY:
            # Redirect to the main page with the passkey in the query string to activate admin view
            return redirect(url_for('index', passkey=ADMIN_PASSKEY, message="Admin view activated."))
        else:
            return redirect(url_for('index', message="Authentication failed. Invalid passkey."))

    # --- Dynamic Content Generation ---
    table_rows = ""
    open_slots_options = "<option value='' disabled selected>Select Slot ID to Claim</option>"
    
    for index, row in df.iterrows():
        status = row['Status']
        
        # Build options for the claim form dropdown (only for public view)
        if status == 'Open':
            open_slots_options += f"<option value='{row['ID']}'>{row['ID']} - {row['Event Name']} ({row['Date']})</option>"

        status_class = 'bg-green-100 text-green-800' if status == 'Open' else 'bg-red-100 text-red-800'
        
        # Determine what to show in the 'Covering Member' column
        if is_admin or status == 'Open':
            # Admin always sees the name; Public sees 'None' if open
            member_cell = row['Covering Member'] 
        else:
            # Public view hides the name for Covered slots
            member_cell = '—' 
        
        table_rows += f"""
        <tr class="hover:bg-gray-50 transition duration-150">
            <td class="p-4 whitespace-nowrap text-sm font-medium text-gray-900">{row['ID']}</td>
            <td class="p-4 whitespace-nowrap text-sm text-gray-500">{row['Event Name']}</td>
            <td class="p-4 whitespace-nowrap text-sm text-gray-500">{row['Date']}</td>
            <td class="p-4 whitespace-nowrap text-sm text-gray-500">{row['Time Slot']}</td>
            <td class="p-4 whitespace-nowrap">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {status_class}">
                    {status}
                </span>
            </td>
            <td class="p-4 whitespace-nowrap text-sm text-gray-700 font-semibold">{member_cell}</td>
        </tr>
        """

    # --- Conditional HTML Blocks (Admin vs. Public) ---
    if is_admin:
        header_text = 'Admin Dashboard'
        sub_text = 'Viewing all event data, including covered members. To return to the public member view, remove the `?passkey=...` from the URL.'
        claim_form = '' # Hide claim form for admin view
        admin_info = """
            <div class="mb-8 border border-yellow-200 p-6 rounded-lg bg-yellow-50 text-yellow-800 font-semibold">
                You are currently viewing the **Admin Dashboard**. All data is visible.
                <a href="/" class="text-blue-600 hover:text-blue-800 underline ml-2">Switch to Public View</a>
            </div>
        """
        table_title = 'Full Event Schedule'
    else:
        header_text = 'Event Coverage Dashboard'
        sub_text = f'Claim an open slot by filling out the form below. Changes are saved directly to <code>{EXCEL_FILE}</code>.'
        # Public Claim Form
        claim_form = f"""
            <!-- Claim Slot Form -->
            <div class="mb-8 border border-blue-200 p-6 rounded-lg bg-blue-50">
                <h2 class="text-xl font-semibold mb-4 text-blue-700">Claim an Event Slot</h2>
                <form action="{url_for('claim_slot')}" method="post" class="space-y-4">
                    <div>
                        <label for="slot_id" class="block text-sm font-medium text-gray-700">Select Slot</label>
                        <select id="slot_id" name="slot_id" required 
                                class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm rounded-md shadow-sm">
                            {open_slots_options}
                        </select>
                    </div>
                    <div>
                        <label for="member_name" class="block text-sm font-medium text-gray-700">Your Name (e.g., Jane Doe)</label>
                        <input type="text" id="member_name" name="member_name" required 
                               class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                               placeholder="Enter your name">
                    </div>
                    <button type="submit" 
                            class="w-full justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition duration-150 ease-in-out">
                        Claim Slot
                    </button>
                </form>
            </div>
        """
        # Admin Login Form (Hidden by default, triggered by JS)
        admin_info = f"""
            <div class="text-right mt-4">
                <button onclick="document.getElementById('admin-login-modal').classList.remove('hidden')" 
                        class="text-sm text-gray-500 hover:text-gray-700 underline">
                    Admin Login
                </button>
            </div>
            
            <!-- Admin Login Modal -->
            <div id="admin-login-modal" class="fixed inset-0 bg-gray-600 bg-opacity-75 hidden flex items-center justify-center p-4 z-50">
                <div class="bg-white p-6 rounded-lg shadow-xl w-full max-w-sm">
                    <h3 class="text-lg font-semibold mb-4 text-gray-800">Admin Access Required</h3>
                    <form action="{url_for('index')}" method="post" class="space-y-4">
                        <input type="password" name="admin_passkey" placeholder="Enter Admin Passkey" required 
                               class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
                        <div class="flex justify-end space-x-2 mt-4">
                            <button type="button" onclick="document.getElementById('admin-login-modal').classList.add('hidden')" 
                                    class="py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50">
                                Cancel
                            </button>
                            <button type="submit" 
                                    class="py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700">
                                Login
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        """
        table_title = 'Event Schedule (Covered Members Hidden)'


    # HTML template content (using Tailwind CSS for aesthetics)
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Photography Club Coverage Tracker</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
            body {{ font-family: 'Inter', sans-serif; background-color: #f7f9fb; }}
        </style>
    </head>
    <body class="p-4 sm:p-8">
        <div class="max-w-4xl mx-auto bg-white p-6 sm:p-8 rounded-xl shadow-2xl">
            <h1 class="text-3xl font-bold mb-2 text-gray-800">{header_text}</h1>
            <p class="text-gray-500 mb-6">{sub_text}</p>
            
            {admin_info}
            
            {claim_form}
            
            <!-- Event Schedule Table -->
            <h2 class="text-xl font-semibold mb-4 text-gray-800">{table_title}</h2>
            <div class="overflow-x-auto shadow-md rounded-lg border border-gray-200">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                            <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Event Name</th>
                            <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                            <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Slot</th>
                            <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                            <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Covering Member</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {table_rows}
                    </tbody>
                </table>
            </div>
            
            <!-- Simple Message Box for Feedback -->
            <div id="message-box" class="fixed bottom-4 right-4 bg-yellow-400 text-gray-800 p-3 rounded-lg shadow-xl hidden transition transform ease-in-out duration-300"></div>

            <script>
                // JavaScript to show a success message (if a query parameter is present)
                document.addEventListener('DOMContentLoaded', () => {{
                    const urlParams = new URLSearchParams(window.location.search);
                    const message = urlParams.get('message');
                    const msgBox = document.getElementById('message-box');
                    const adminKey = urlParams.get('passkey');

                    if (message) {{
                        msgBox.textContent = decodeURIComponent(message);
                        // Change color if it's an error message
                        if (message.includes("Error:") || message.includes("failed")) {{
                            msgBox.classList.add('bg-red-400', 'text-white');
                            msgBox.classList.remove('bg-yellow-400', 'text-gray-800');
                        }}
                        
                        msgBox.classList.remove('hidden');
                        msgBox.classList.add('translate-y-0');
                        
                        // Hide after 5 seconds
                        setTimeout(() => {{
                            msgBox.classList.add('hidden');
                            msgBox.classList.remove('translate-y-0');
                        }}, 5000);
                    }}
                    
                    // Automatically hide the modal if we successfully logged in and are now on admin view
                    if (adminKey === '{ADMIN_PASSKEY}') {{
                        const modal = document.getElementById('admin-login-modal');
                        if (modal) {{
                            modal.classList.add('hidden');
                        }}
                    }}
                }});
            </script>
        </div>
    </body>
    </html>
    """
    
    return render_template_string(html_content)

@app.route('/claim_slot', methods=['POST'])
def claim_slot():
    """Handles the form submission and updates the Excel file."""
    try:
        slot_id = int(request.form.get('slot_id'))
        member_name = request.form.get('member_name').strip()
        
        if not member_name:
            # Redirect with an error message using a query parameter
            return redirect(url_for('index', message="Error: Member name cannot be empty!"))

        df = load_data()
        
        # Check if the slot exists and is open
        if slot_id in df.index and df.loc[slot_id, 'Status'] == 'Open':
            # Update the DataFrame
            df.loc[slot_id, 'Status'] = 'Covered'
            df.loc[slot_id, 'Covering Member'] = member_name
            
            # Save the updated data back to Excel
            save_data(df)
            
            success_msg = f"Success! Slot {slot_id} claimed by {member_name}."
            return redirect(url_for('index', message=success_msg))
        
        elif slot_id in df.index and df.loc[slot_id, 'Status'] == 'Covered':
             return redirect(url_for('index', message=f"Slot {slot_id} is already covered!"))
        
        else:
             return redirect(url_for('index', message=f"Error: Slot ID {slot_id} not found or invalid."))

    except ValueError:
        return redirect(url_for('index', message="Error: Invalid Slot ID selected."))
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return redirect(url_for('index', message=f"An unexpected error occurred: {e}"))

# --- Run the App ---
if __name__ == '__main__':
    # Initial data load check to ensure the file exists or is created on startup
    load_data()
    print("\n--- Event Coverage Manager Started ---")
    print(f"Data File: {EXCEL_FILE}")
    print("Web App running at: http://127.0.0.1:5000/")
    print(f"Admin Access Key: {ADMIN_PASSKEY}")
    print("Press Ctrl+C to stop the server.")
    # Production deployment environments set the port via an environment variable
    port = int(os.environ.get('PORT', 5000))
    # Note: When deploying with Gunicorn (via the Procfile below), this 'app.run' 
    # block is often skipped in favor of Gunicorn handling the server startup.
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)