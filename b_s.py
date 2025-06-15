#!/usr/bin/env python3
"""
test_b_s.py - Test script to verify placeholder replacement works
This file demonstrates that the VBS script can successfully replace placeholder values
"""

import tkinter as tk
from tkinter import ttk
import threading
import time

# Configuration placeholders (will be replaced by bot_starter.vbs)
BOT_NAME = "PLACEHOLDER_BOT_NAME"
USERNAME = "PLACEHOLDER_USERNAME"
PASSWORD = "PLACEHOLDER_PASSWORD"
ROOM_ID = "PLACEHOLDER_ROOM_ID"
HOMESERVER = "PLACEHOLDER_HOMESERVER"

class TestWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Matrix Bot Configuration Test")
        self.root.geometry("600x400")
        self.root.configure(bg='#2b2b2b')
        
        # Create main frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Matrix Bot Configuration Test", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20), sticky=tk.W)
        
        # Status
        self.status_var = tk.StringVar()
        self.status_var.set("Checking configuration...")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, 
                                font=('Arial', 10))
        status_label.grid(row=1, column=0, columnspan=2, pady=(0, 20), sticky=tk.W)
        
        # Configuration display
        config_frame = ttk.LabelFrame(main_frame, text="Configuration Values", padding="10")
        config_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        config_frame.columnconfigure(1, weight=1)
        
        # Bot Name
        ttk.Label(config_frame, text="Bot Name:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.bot_name_var = tk.StringVar(value=BOT_NAME)
        ttk.Label(config_frame, textvariable=self.bot_name_var, foreground='blue').grid(row=0, column=1, sticky=tk.W)
        
        # Username
        ttk.Label(config_frame, text="Username:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.username_var = tk.StringVar(value=USERNAME)
        ttk.Label(config_frame, textvariable=self.username_var, foreground='blue').grid(row=1, column=1, sticky=tk.W, pady=(5, 0))
        
        # Password (masked)
        ttk.Label(config_frame, text="Password:", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.password_var = tk.StringVar()
        self.update_password_display()
        ttk.Label(config_frame, textvariable=self.password_var, foreground='blue').grid(row=2, column=1, sticky=tk.W, pady=(5, 0))
        
        # Room ID
        ttk.Label(config_frame, text="Room ID:", font=('Arial', 10, 'bold')).grid(row=3, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.room_id_var = tk.StringVar(value=ROOM_ID)
        ttk.Label(config_frame, textvariable=self.room_id_var, foreground='blue').grid(row=3, column=1, sticky=tk.W, pady=(5, 0))
        
        # Homeserver
        ttk.Label(config_frame, text="Homeserver:", font=('Arial', 10, 'bold')).grid(row=4, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.homeserver_var = tk.StringVar(value=HOMESERVER)
        ttk.Label(config_frame, textvariable=self.homeserver_var, foreground='blue').grid(row=4, column=1, sticky=tk.W, pady=(5, 0))
        
        # Results frame
        results_frame = ttk.LabelFrame(main_frame, text="Test Results", padding="10")
        results_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        results_frame.columnconfigure(0, weight=1)
        
        # Results text
        self.results_text = tk.Text(results_frame, height=8, width=70, wrap=tk.WORD,
                                   bg='#1e1e1e', fg='#ffffff', font=('Consolas', 9))
        self.results_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Scrollbar for results
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.results_text.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.results_text.configure(yscrollcommand=scrollbar.set)
        
        # Buttons frame
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.grid(row=4, column=0, columnspan=2, pady=(20, 0))
        
        # Test button
        test_button = ttk.Button(buttons_frame, text="Run Configuration Test", 
                                command=self.run_test)
        test_button.grid(row=0, column=0, padx=(0, 10))
        
        # Close button
        close_button = ttk.Button(buttons_frame, text="Close", 
                                 command=self.root.quit)
        close_button.grid(row=0, column=1)
        
        # Auto-run test after a short delay
        self.root.after(1000, self.run_test)
    
    def update_password_display(self):
        """Update password display (masked for security)"""
        if PASSWORD.startswith("PLACEHOLDER"):
            self.password_var.set(PASSWORD)
        else:
            # Mask the password but show first 2 and last 2 characters
            if len(PASSWORD) > 4:
                masked = PASSWORD[:2] + "*" * (len(PASSWORD) - 4) + PASSWORD[-2:]
            else:
                masked = "*" * len(PASSWORD)
            self.password_var.set(masked)
    
    def run_test(self):
        """Run configuration test"""
        def test_thread():
            self.results_text.delete(1.0, tk.END)
            self.add_result("Starting configuration test...\n")
            
            # Check if placeholders were replaced
            placeholder_count = 0
            replaced_count = 0
            
            configs = {
                "BOT_NAME": BOT_NAME,
                "USERNAME": USERNAME,
                "PASSWORD": PASSWORD,
                "ROOM_ID": ROOM_ID,
                "HOMESERVER": HOMESERVER
            }
            
            self.add_result("Checking configuration values:\n")
            self.add_result("-" * 50 + "\n")
            
            for key, value in configs.items():
                if value.startswith("PLACEHOLDER_"):
                    placeholder_count += 1
                    self.add_result(f"❌ {key}: {value} (NOT REPLACED)\n")
                else:
                    replaced_count += 1
                    display_value = value
                    if key == "PASSWORD":
                        # Mask password in results
                        if len(value) > 4:
                            display_value = value[:2] + "*" * (len(value) - 4) + value[-2:]
                        else:
                            display_value = "*" * len(value)
                    self.add_result(f"✅ {key}: {display_value} (REPLACED)\n")
            
            self.add_result("\n" + "=" * 50 + "\n")
            self.add_result(f"RESULTS SUMMARY:\n")
            self.add_result(f"Replaced: {replaced_count}/5 configurations\n")
            self.add_result(f"Still placeholders: {placeholder_count}/5 configurations\n")
            
            if placeholder_count == 0:
                self.add_result("\n🎉 SUCCESS: All placeholders were replaced!\n")
                self.add_result("The VBS script replacement mechanism is working correctly.\n")
                self.status_var.set("✅ Configuration test PASSED - All values replaced")
            elif placeholder_count == 5:
                self.add_result("\n⚠️  INFO: All values are still placeholders.\n")
                self.add_result("This is expected if running the original file before VBS replacement.\n")
                self.status_var.set("ℹ️ Original file detected - Placeholders not yet replaced")
            else:
                self.add_result("\n❌ PARTIAL: Some placeholders were replaced, others were not.\n")
                self.add_result("This might indicate an issue with the replacement process.\n")
                self.status_var.set("⚠️ Configuration test PARTIAL - Some values missing")
            
            # Test timestamp
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self.add_result(f"\nTest completed at: {current_time}\n")
        
        # Run test in separate thread to avoid blocking UI
        threading.Thread(target=test_thread, daemon=True).start()
    
    def add_result(self, text):
        """Add text to results display"""
        self.results_text.insert(tk.END, text)
        self.results_text.see(tk.END)
        self.root.update_idletasks()
    
    def run(self):
        """Start the application"""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            print("Application closed by user")

def main():
    """Main function"""
    print("Matrix Bot Configuration Test")
    print("=" * 40)
    print(f"Bot Name: {BOT_NAME}")
    print(f"Username: {USERNAME}")
    print(f"Password: {'*' * len(PASSWORD) if not PASSWORD.startswith('PLACEHOLDER') else PASSWORD}")
    print(f"Room ID: {ROOM_ID}")
    print(f"Homeserver: {HOMESERVER}")
    print("=" * 40)
    
    # Start GUI
    app = TestWindow()
    app.run()

if __name__ == "__main__":
    main()
