import os
import time
import shutil
import re
from datetime import datetime, timezone, timedelta, date
import sqlite3
from urllib.parse import unquote, quote
from multiprocessing import Pool
import threading

import wx
import wx.adv
import requests
from bs4 import BeautifulSoup

import replay_result
from version_config import version_config

class SortableListCtrl(wx.ListCtrl):
    def __init__(self, parent, columns, style=wx.LC_REPORT | wx.BORDER_SUNKEN, with_icons=False, force_string_sort_cols=None):
        super().__init__(parent, style=style)
        self.columns = columns
        self.sort_column = -1
        self.sort_ascending = True
        self.with_icons = with_icons
        self.item_colors = {}
        self.force_string_sort_cols = force_string_sort_cols or []  # Columns to always sort as strings
        
        if self.with_icons:
            self.image_list = wx.ImageList(16, 16)
            self.folder_idx = self.image_list.Add(wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, (16, 16)))
            self.file_idx = self.image_list.Add(wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, (16, 16)))
            self.rep_file_idx = self.image_list.Add(wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, (16, 16)))
            self.SetImageList(self.image_list, wx.IMAGE_LIST_SMALL)
        
        self.setup_columns()
        self.Bind(wx.EVT_LIST_COL_CLICK, self.on_column_click)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)
    
    def setup_columns(self):
        for idx, (header, width) in enumerate(self.columns):
            self.InsertColumn(idx, header, width=width)
    
    def on_column_click(self, event):
        column = event.GetColumn()
        
        if self.sort_column == column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = True
        
        self.sort_items(column, self.sort_ascending)
    
    def SetItemTextColour(self, item, colour):
            super().SetItemTextColour(item, colour)
            self.item_colors[item] = colour

    def sort_items(self, column, ascending):
        items = []
        for i in range(self.GetItemCount()):
            item_data = [self.GetItemText(i, col) for col in range(len(self.columns))]
            item_type = self.GetItemData(i) if self.with_icons else None
            item_color = self.item_colors.get(i) if hasattr(self, 'item_colors') else None
            items.append((item_data, item_type, item_color))
        
        if not items:
            return
        
        try:
            # Determine if we should force string sorting for this column
            force_string = column in self.force_string_sort_cols
            
            # For file lists: separate folders and files
            if self.with_icons:
                parent_dir = []
                folders = []
                files = []
                
                for item in items:
                    if item[1] == 0:
                        parent_dir.append(item)
                    elif item[1] == 1:
                        folders.append(item)
                    else:
                        files.append(item)
                
                # Sort folders and files separately
                sort_key = lambda x: x[0][column].lower() if force_string or column != 1 else float(x[0][column] or 0)
                
                folders.sort(key=sort_key, reverse=not ascending)
                files.sort(key=sort_key, reverse=not ascending)
                
                sorted_items = parent_dir + folders + files
            else:
                # For other lists (like properties_list)
                sort_key = lambda x: x[0][column].lower()  # Always sort as string for properties_list
                sorted_items = sorted(items, key=sort_key, reverse=not ascending)
            
            # Reload sorted items (same as before)
            self.DeleteAllItems()

            self.item_colors = {}
            
            for new_index, (item_data, item_type, item_color) in enumerate(sorted_items):
                if self.with_icons:
                   if item_type == 0:  # Parent
                       index = self.InsertItem(self.GetItemCount(), item_data[0], self.folder_idx)
                   elif item_type == 1:  # Folder
                       index = self.InsertItem(self.GetItemCount(), item_data[0], self.folder_idx)
                   else:  # File
                       icon = self.rep_file_idx if item_data[0].lower().endswith('.rep') else self.file_idx
                       index = self.InsertItem(self.GetItemCount(), item_data[0], icon)
                else:
                    index = self.InsertItem(self.GetItemCount(), item_data[0])
                
                # Set other columns
                for col in range(1, len(item_data)):
                    self.SetItem(index, col, item_data[col])
                
                # Restore color if it existed
                if item_color is not None:
                    super().SetItemTextColour(index, item_color)
                    self.item_colors[index] = item_color
                
                # Store item type if using icons
                if self.with_icons:
                    self.SetItemData(index, item_type)
        
        except ValueError:
            # Fallback to string sorting if numeric conversion fails
            if self.with_icons:
                folders.sort(key=lambda x: x[0][column].lower(), reverse=not ascending)
                files.sort(key=lambda x: x[0][column].lower(), reverse=not ascending)
                sorted_items = parent_dir + folders + files
            else:
                sorted_items = sorted(items, key=lambda x: x[0][column].lower(), reverse=not ascending)
            
            self.DeleteAllItems()
            for item_data, item_type in sorted_items:
                if self.with_icons:
                    if item_type == 0:
                        index = self.InsertItem(self.GetItemCount(), item_data[0], self.folder_idx)
                    elif item_type == 1:
                        index = self.InsertItem(self.GetItemCount(), item_data[0], self.folder_idx)
                    else:
                        icon = self.rep_file_idx if item_data[0].lower().endswith('.rep') else self.file_idx
                        index = self.InsertItem(self.GetItemCount(), item_data[0], icon)
                else:
                    index = self.InsertItem(self.GetItemCount(), item_data[0])
                
                for col in range(1, len(item_data)):
                    self.SetItem(index, col, item_data[col])
                
                if self.with_icons:
                    self.SetItemData(index, item_type)
    
    def on_right_click(self, event):
        index = event.GetIndex()
        if index != -1:
            position = wx.GetMousePosition()
            position = self.ScreenToClient(position)
            item, flags, col = self.HitTestSubItem(position)
            
            menu = wx.Menu()
            copy_item = menu.Append(wx.ID_ANY, "Copy Text")
            self.GetTopLevelParent().Bind(wx.EVT_MENU, lambda e: self.on_copy(index, col), copy_item)
            self.PopupMenu(menu)
    
    def on_copy(self, row, col):
        text = self.GetItem(row, col).Text
        clipboard = wx.Clipboard.Get()
        if clipboard.Open():
            clipboard.SetData(wx.TextDataObject(text))
            clipboard.Close()

class ReplayBrowserTab(wx.Panel):
    def __init__(self, parent, tab_type="local"):
        super().__init__(parent)
        self.tab_type = tab_type
        self.current_directory = ""
        self.selected_file_path = ""
        self.filter_bin_only = True
        self.sort_column = -1
        self.sort_ascending = True
        self.fetch_id = 0
        self.setup_ui()
        if tab_type == "local":
            replays_dir = os.path.join(os.environ['USERPROFILE'], 'Documents\\Command and Conquer Generals Zero Hour Data\\Replays')
            if os.path.isdir(replays_dir):
                self.load_directory(replays_dir)
            else:
                self.load_directory(os.getcwd())
        if tab_type == "online":
            self.current_directories = []
            self.directories_to_fetch = []
            self.all_files = []

            self.setup_online_controls()
    
    def setup_ui(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Address bar
        address_hbox = wx.BoxSizer(wx.HORIZONTAL)
        
        if self.tab_type == "local":
            address_label = wx.StaticText(self, label="Local Directory:" if self.tab_type == "local" else "")
            address_hbox.Add(address_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=2)
            self.dir_path = wx.DirPickerCtrl(self, message="Choose a directory", style=wx.DIRP_USE_TEXTCTRL)
            self.dir_path.Bind(wx.EVT_DIRPICKER_CHANGED, self.on_select_directory)
            address_hbox.Add(self.dir_path, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)
        
        vbox.Add(address_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)
        
        # Splitter for left/right panels
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        self.splitter.SetMinimumPaneSize(100)
        
        # Left panel
        left_panel = wx.Panel(self.splitter)
        left_vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Search bar
        self.search_ctrl = wx.SearchCtrl(left_panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetDescriptiveText("Search files...")
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search)
        self.search_ctrl.Bind(wx.EVT_SEARCH_CANCEL, self.on_search_cancel)
        left_vbox.Add(self.search_ctrl, proportion=0, flag=wx.EXPAND | wx.LEFT | wx.BOTTOM, border=2)
        
        # File count label
        self.file_count_label = wx.StaticText(left_panel, label="")
        left_vbox.Add(self.file_count_label, proportion=0, flag=wx.EXPAND | wx.ALL, border=4)
        
        # File list
        if self.tab_type == "local":
            file_list_columns = [("Filename", 200), ("File Size (KB)", 50), ("Date Modified", 150)]
        elif self.tab_type == "online":
            file_list_columns = [("Filename", 200), ("File Size (KB)", 50), ("Date Modified", 150), ("GT Dir", 150), ("URL", 150)]
        self.file_list = SortableListCtrl(left_panel, file_list_columns, with_icons=True)
        self.file_list.SetMinSize((300, -1))

        self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_file_selected)
        self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_file_deselected)
        self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)
        left_vbox.Add(self.file_list, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.TOP | wx.BOTTOM, border=2)
        
        # Action buttons
        buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)
        if self.tab_type == "local":
            self.action_btn = wx.Button(left_panel, label="Rename")
            self.action_all_btn = wx.Button(left_panel, label="Rename All")
            self.move_btn = wx.Button(left_panel, label="Move")
            self.delete_btn = wx.Button(left_panel, label="Delete")
            self.move_btn.Bind(wx.EVT_BUTTON, self.on_move_files)
            self.delete_btn.Bind(wx.EVT_BUTTON, self.on_delete_files)
            buttons_hbox.Add(self.move_btn, proportion=0, flag=wx.ALL, border=2)
            buttons_hbox.Add(self.delete_btn, proportion=0, flag=wx.ALL, border=2)
            self.move_btn.Disable()
            self.delete_btn.Disable()
        else:
            self.action_btn = wx.Button(left_panel, label="Download")
            self.action_all_btn = wx.Button(left_panel, label="Download All")
            
        self.action_btn.Bind(wx.EVT_BUTTON, self.on_action_file)
        self.action_all_btn.Bind(wx.EVT_BUTTON, self.on_action_all_files)
        self.action_btn.Disable()
        self.action_all_btn.Disable()

        
        buttons_hbox.Add(self.action_btn, proportion=0, flag=wx.ALL, border=2)
        buttons_hbox.Add(self.action_all_btn, proportion=0, flag=wx.ALL, border=2)
        left_vbox.Add(buttons_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)
        left_panel.SetSizer(left_vbox)
        
        # Right panel
        right_panel = wx.Panel(self.splitter)
        right_vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Right splitter for properties/details
        self.right_splitter = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        self.right_splitter.SetMinimumPaneSize(50)
        
        # Properties panel
        properties_panel = wx.Panel(self.right_splitter)
        properties_sizer = wx.BoxSizer(wx.VERTICAL)
        self.properties_list = SortableListCtrl(properties_panel, [("Property", 150), ("Value", 400)], force_string_sort_cols=[1])
        properties_sizer.Add(self.properties_list, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        properties_panel.SetSizer(properties_sizer)
        
        # Details panel
        details_panel = wx.Panel(self.right_splitter)
        details_sizer = wx.BoxSizer(wx.VERTICAL)
        details_columns = [
            ('Team', 50), 
            ('Hex IP', 80), 
            ('Player Names', 100), 
            ('Faction', 180), 
            ('Surrender/Exit?', 90), 
            ('Surrender', 90), 
            ('Exit', 90), 
            ('Idle/Kicked?', 90), 
            ('Last CRC', 90), 
            ('Placement', 90),
        ] 

        self.details_list = SortableListCtrl(details_panel, details_columns)
        details_sizer.Add(self.details_list, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        details_panel.SetSizer(details_sizer)
        
        self.right_splitter.SplitHorizontally(properties_panel, details_panel, sashPosition=350)
        right_vbox.Add(self.right_splitter, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)
        right_panel.SetSizer(right_vbox)
        
        self.splitter.SplitVertically(left_panel, right_panel, sashPosition=350)
        vbox.Add(self.splitter, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)
        self.SetSizer(vbox)

        font = wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        if 'Arial' in wx.FontEnumerator().GetFacenames():
            font.SetFaceName('Arial')
        self.properties_list.SetFont(font)
        self.details_list.SetFont(font)

    def load_directory(self, directory_path):
        if self.tab_type != "local":
            return
            
        self.dir_path.SetPath(directory_path)
        self.current_directory = directory_path
        self.file_list.DeleteAllItems()
        
        try:
            # Add parent directory if not at root
            if os.path.abspath(directory_path) != os.path.abspath(os.path.dirname(directory_path)):
                index = self.file_list.InsertItem(0, "..", self.file_list.folder_idx)
                self.file_list.SetItem(index, 1, "")
                self.file_list.SetItem(index, 2, "")
                self.file_list.SetItemData(index, 0)  # 0 for parent directory

            items = os.listdir(directory_path)
            directories = []
            files = []
            
            for item in items:
                item_path = os.path.join(directory_path, item)
                if os.path.isdir(item_path):
                    directories.append(item)
                elif not self.filter_bin_only or item.lower().endswith('.rep'):
                    files.append(item)
            
            directories.sort()
            files.sort()
            
            if files:
                self.action_all_btn.Enable()
            else:
                self.action_all_btn.Disable()
            
            # Add directories with type=1
            for directory in directories:
                dir_path = os.path.join(directory_path, directory)
                index = self.file_list.InsertItem(self.file_list.GetItemCount(), directory, self.file_list.folder_idx)
                self.file_list.SetItem(index, 1, "")
                mod_time = os.path.getmtime(dir_path)
                date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mod_time))
                self.file_list.SetItem(index, 2, date_str)
                self.file_list.SetItemData(index, 1)  # 1 for folder
            
            # Add files with type=2
            for file in files:
                file_path = os.path.join(directory_path, file)
                # Determine icon based on file extension
                icon_idx = self.file_list.rep_file_idx if file.lower().endswith('.rep') else self.file_list.file_idx
                
                index = self.file_list.InsertItem(self.file_list.GetItemCount(), file, icon_idx)
                size_kb = os.path.getsize(file_path) / 1024
                self.file_list.SetItem(index, 1, f"{size_kb:.1f}")
                mod_time = os.path.getmtime(file_path)
                date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mod_time))
                self.file_list.SetItem(index, 2, date_str)
                self.file_list.SetItemData(index, 2)  # 2 for file
            
            # Update file count
            rep_files = [f for f in files if f.lower().endswith('.rep')]
            self.file_count_label.SetLabel(f"Found: {len(rep_files)} replays")
            
        except Exception as e:
            wx.MessageBox(f"Error loading directory: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
    
    def on_select_directory(self, event):
        selected_path = self.dir_path.GetPath()
        self.load_directory(selected_path)
    
    def on_item_activated(self, event):
        index = event.GetIndex()
        item_type = self.file_list.GetItemData(index)
        if item_type == 0:  # Parent directory
            parent_dir = os.path.dirname(self.current_directory)
            self.properties_list.DeleteAllItems()
            self.details_list.DeleteAllItems()
            self.search_ctrl.Clear()
            self.load_directory(parent_dir)
        elif item_type == 1:  # Directory
            new_dir = os.path.join(self.current_directory, self.file_list.GetItemText(index))
            self.properties_list.DeleteAllItems()
            self.details_list.DeleteAllItems()
            self.search_ctrl.Clear()
            self.load_directory(new_dir)
    
    def on_search(self, event):
        search_text = self.search_ctrl.GetValue().lower()
        self.filter_files(search_text)
    
    def on_search_cancel(self, event):
        self.search_ctrl.SetValue("")
        if self.tab_type == "local":
            self.load_directory(self.current_directory)
        else:
            self.display_files(self.all_files)
    
    def filter_files(self, search_text):
        if self.tab_type == "local":
            self.file_list.DeleteAllItems()
            try:
                if os.path.abspath(self.current_directory) != os.path.abspath(os.path.dirname(self.current_directory)):
                    index = self.file_list.InsertItem(0, "..", self.file_list.folder_idx)
                    self.file_list.SetItem(index, 1, "")
                    self.file_list.SetItem(index, 2, "")
                    self.file_list.SetItemData(index, 0)  # 0 for parent directory
                
                items = os.listdir(self.current_directory)
                directories = []
                files = []
                
                for item in items:
                    item_path = os.path.join(self.current_directory, item)
                    if os.path.isdir(item_path) and search_text in item.lower():
                        directories.append(item)
                    elif (not self.filter_bin_only or item.lower().endswith('.rep')) and search_text in item.lower():
                        files.append(item)
                
                directories.sort()
                files.sort()
                
                # Add matching directories with type=1
                for directory in directories:
                    dir_path = os.path.join(self.current_directory, directory)
                    index = self.file_list.InsertItem(self.file_list.GetItemCount(), directory, self.file_list.folder_idx)
                    self.file_list.SetItem(index, 1, "")
                    mod_time = os.path.getmtime(dir_path)
                    date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mod_time))
                    self.file_list.SetItem(index, 2, date_str)
                    self.file_list.SetItemData(index, 1)  # 1 for folder
                
                # Add matching files with type=2
                for file in files:
                    file_path = os.path.join(self.current_directory, file)
                    icon_idx = self.file_list.rep_file_idx if file.lower().endswith('.rep') else self.file_list.file_idx
                    
                    index = self.file_list.InsertItem(self.file_list.GetItemCount(), file, icon_idx)
                    size_kb = os.path.getsize(file_path) / 1024
                    self.file_list.SetItem(index, 1, f"{size_kb:.1f}")
                    mod_time = os.path.getmtime(file_path)
                    date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mod_time))
                    self.file_list.SetItem(index, 2, date_str)
                    self.file_list.SetItemData(index, 2)  # 2 for file
                
                rep_files = [f for f in files if f.lower().endswith('.rep')]
                self.file_count_label.SetLabel(f"Found: {len(rep_files)} replays")
                
            except Exception as e:
                wx.MessageBox(f"Error while searching: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
        elif self.tab_type == 'online':
            self.file_list.DeleteAllItems()  
            search_text = search_text.lower()
            for name, size, date, gt_dir, file_url in self.all_files:
                if search_text in name.lower():
                    icon = self.file_list.rep_file_idx if name.lower().endswith('.rep') else self.file_list.file_idx
                    idx = self.file_list.InsertItem(self.file_list.GetItemCount(), name, icon)
                    self.file_list.SetItem(idx, 1, str(size))
                    self.file_list.SetItem(idx, 2, date)
                    self.file_list.SetItem(idx, 3, gt_dir)
                    self.file_list.SetItem(idx, 4, file_url)
                    self.file_list.SetItemData(idx, 2)
            self.file_count_label.SetLabel(f"Found: {self.file_list.GetItemCount()} replays")

    def on_file_selected(self, event):
        index = event.GetIndex()
        item_type = self.file_list.GetItemData(index)
        if item_type in [1, 2]:
            if self.file_list.GetSelectedItemCount() > 1:
                self.properties_list.DeleteAllItems()
                self.details_list.DeleteAllItems()
                self.selected_file_path = ""
            else:
                if item_type == 2:

                    self.action_btn.Enable()
                    
                    filename = self.file_list.GetItemText(index)
                    if self.tab_type == "local":
                        self.selected_file_path = os.path.join(self.current_directory, filename)
                        self.move_btn.Enable()
                        self.delete_btn.Enable() 
                    elif self.tab_type == 'online':
                        self.selected_file_path = self.file_list.GetItem(index, 4).GetText()
                    self.properties_list.DeleteAllItems()
                    self.details_list.DeleteAllItems()
                    
                    self.populate_loading()
                    
                    self.fetch_id += 1  # Invalidate previous fetch
                    current_id = self.fetch_id
                    if self.tab_type == "local":
                        if os.path.exists(self.selected_file_path):
                            threading.Thread(target=self.fetch_info, args=(self.selected_file_path, 'local', current_id), daemon=True).start()
                    elif self.tab_type == 'online':
                        threading.Thread(target=self.fetch_info, args=(self.selected_file_path, 'online', current_id), daemon=True).start()
        else:
            self.action_btn.Disable()
            if self.tab_type == "local":
                self.move_btn.Disable()
                self.delete_btn.Disable()
            self.selected_file_path = ""
            self.properties_list.DeleteAllItems()
            self.details_list.DeleteAllItems()
    
    def populate_loading(self):
        self.properties_list.DeleteAllItems()
        self.properties_list.InsertItem(0, "Loading...")
        self.properties_list.SetItem(0, 1, "Loading...")
        self.details_list.DeleteAllItems()
        self.details_list.InsertItem(0, "Loading...")
        # index = self.details_list.InsertItem(0, "Loading")
        # for col in range(1, 10):
        #     self.details_list.SetItem(index, col, "Loading")

    def on_file_deselected(self, event):
        if self.file_list.GetSelectedItemCount() == 0:
            self.action_btn.Disable()
            if self.tab_type == "local":
                self.move_btn.Disable()
                self.delete_btn.Disable()
            self.selected_file_path = ""
            self.properties_list.DeleteAllItems()
            self.details_list.DeleteAllItems()

        elif self.file_list.GetSelectedItemCount() == 1:
            index = self.file_list.GetFirstSelected()
            if index != -1:
                item_type = self.file_list.GetItemData(index)
                if item_type == 2:
                    filename = self.file_list.GetItemText(index)
                    if self.tab_type == "local":
                        self.selected_file_path = os.path.join(self.current_directory, filename)
                    elif self.tab_type == 'online':
                        self.selected_file_path = self.file_list.GetItem(index, 4).GetText()
                    self.properties_list.DeleteAllItems()
                    self.details_list.DeleteAllItems()
                    
                    self.populate_loading()
                    
                    self.fetch_id += 1  # Invalidate previous fetch
                    current_id = self.fetch_id
                    if self.tab_type == "local":
                        if os.path.exists(self.selected_file_path):
                            threading.Thread(target=self.fetch_info, args=(self.selected_file_path, 'local', current_id), daemon=True).start()
                    elif self.tab_type == 'online':
                        threading.Thread(target=self.fetch_info, args=(self.selected_file_path, 'online', current_id), daemon=True).start()
    
    def fetch_info(self, selected_file, mode, fetch_id):
        # If fetch ID is outdated, cancel
        if fetch_id != self.fetch_id:
            return
        file_prop = None
        player_info = None
        try:
            if selected_file.lower().endswith('.rep'):
                rep1 = replay_result.ReplayResultParser(selected_file, mode)
                file_prop = rep1.get_replay_info_gui()
                player_info = rep1.get_players_info_gui()
        except Exception as e:
            wx.MessageBox(f"Error: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
        if file_prop and player_info :
            wx.CallAfter(self.display_file_properties, file_prop, player_info, fetch_id)
        else:
            self.properties_list.DeleteAllItems()
            self.details_list.DeleteAllItems()

    def display_file_properties(self, file_prop, player_info, fetch_id):
        if fetch_id != self.fetch_id:
            return  # This fetch was cancelled
            
        self.properties_list.DeleteAllItems()
        self.details_list.DeleteAllItems()

        ver_str = 'default'
        # Display properties in the list
        for i, (prop, value) in enumerate(file_prop[:-1]):
            if (prop == "SW Restriction") and (value == "Unknown"):
                continue
            index = self.properties_list.InsertItem(self.properties_list.GetItemCount(), prop)
            self.properties_list.SetItem(index, 1, str(value))

            # Set the color based on
            if prop == "Match Result":
                if 'Win' in value:
                    self.properties_list.SetItemTextColour(index, wx.Colour(0, 128, 0))  # green
                else:
                    self.properties_list.SetItemTextColour(index, wx.Colour(200, 0, 0))  # red
            elif prop == "EXE check (1.04)":
                if value == 'Failed':
                    self.properties_list.SetItemTextColour(index, wx.Colour(200, 0, 0))  # red
            elif prop == "INI check (1.04)":
                if value == 'Failed':
                    self.properties_list.SetItemTextColour(index, wx.Colour(200, 0, 0))  # red
            elif prop == 'Version String':
                if value in version_config:
                    ver_str = value
            elif prop == "Player Name":
                self.properties_list.SetItemTextColour(index, wx.Colour(version_config[ver_str]['colors'].get(file_prop[-1][1], ['Unknown', (0, 0, 0)])[1]))
        
        # Add player info to details_list
        for row in player_info:
            if len(row) > 0:
                index = self.details_list.InsertItem(self.details_list.GetItemCount(), str(row[0]))
                color_num = row[-1]
                for col in range(1, min(len(row), self.details_list.GetColumnCount())):
                    self.details_list.SetItem(index, col, str(row[col]))
                self.details_list.SetItemTextColour(index, version_config[ver_str]['colors'].get(color_num, ['Unknown', (0, 0, 0)])[1])
                
    def on_action_file(self, event):
        if self.tab_type == "local":
            self.on_rename_file()
        else:
            self.on_download_file()
    
    def on_action_all_files(self, event):
        if self.tab_type == "local":
            self.on_rename_all_files()
        else:
            self.on_download_all_files()
    
    def on_rename_file(self):
        selected_indices = []
        index = self.file_list.GetFirstSelected()
        while index != -1:
            selected_indices.append(index)
            index = self.file_list.GetNextSelected(index)

        if not selected_indices:
            return

        renamed_files = []

        try:
            for index in selected_indices:
                selected_file = self.file_list.GetItemText(index)
                filepath = os.path.join(self.current_directory, selected_file)
                
                if not filepath.lower().endswith('.rep'):
                    continue
                    
                new_filename = self.rename_file(filepath)
                renamed_files.append(new_filename)

            self.search_ctrl.Clear()
            self.load_directory(self.current_directory)
            for index in range(self.file_list.GetItemCount()):
                new_filename = self.file_list.GetItemText(index)
                if new_filename in renamed_files:
                    self.file_list.Select(index)
                    self.file_list.Focus(index)

            if renamed_files:
                wx.MessageBox(f"{len(renamed_files)} file(s) renamed successfully!", "Success", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(f"Error renaming files: {e}", "Error", wx.OK | wx.ICON_ERROR)
    
    def on_rename_all_files(self):
        item_count = self.file_list.GetItemCount()

        if item_count == 0:
            wx.MessageBox("No files to rename.", "Info", wx.OK | wx.ICON_INFORMATION)
            return

        file_list = []

        for index in range(item_count):
            filename = self.file_list.GetItemText(index)
            filepath = os.path.join(self.current_directory, filename)
            
            if filepath.lower().endswith('.rep') and self.file_list.GetItemData(index) == 2:
                file_list.append(filepath)

        if not file_list:
            wx.MessageBox("No .rep files found for renaming.", "Info", wx.OK | wx.ICON_INFORMATION)
            return

        dlg = wx.ProgressDialog(
            "Renaming Files",
            "Working...",
            maximum=len(file_list),
            parent=self,
            style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL | wx.PD_ELAPSED_TIME
        )

        renamed_files = []

        try:
            for idx, filepath in enumerate(file_list):
                new_filename = self.rename_file(filepath)
                renamed_files.append(new_filename)
                dlg.Update(idx + 1, f"Renaming ({idx + 1}/{len(file_list)})")
                wx.Yield()
                
            self.search_ctrl.Clear()
            self.load_directory(self.current_directory)
            
            for index in range(self.file_list.GetItemCount()):
                new_filename = self.file_list.GetItemText(index)
                if new_filename in renamed_files:
                    self.file_list.Select(index)
                    self.file_list.Focus(index)
                    
            dlg.Update(len(file_list), f"{len(file_list)} files renamed successfully!")
            wx.MessageBox(f"{len(file_list)} file(s) renamed successfully!", "Success", wx.OK | wx.ICON_INFORMATION)
            
        except Exception as e:
            wx.MessageBox(f"Error renaming files: {e}", "Error", wx.OK | wx.ICON_ERROR)
        finally:
            dlg.Destroy()
    
    def rename_file(self, filepath):
        try:
            rep2 = replay_result.ReplayResultParser(filepath)
            base_name = rep2.get_new_replay_name()
            if base_name:
                new_filename = f"{base_name}.rep"
                new_filepath = os.path.join(os.path.dirname(filepath), new_filename)
                current_filename = os.path.basename(filepath)
                
                counter = 1
                while os.path.exists(new_filepath):
                    if new_filename == current_filename:
                        return new_filename
                    else:
                        new_filename = f"{base_name}_{counter}.rep"
                        new_filepath = os.path.join(os.path.dirname(filepath), new_filename)
                        counter += 1

                os.rename(filepath, new_filepath)
                return new_filename
            else:
                self.properties_list.DeleteAllItems()
                self.details_list.DeleteAllItems()
        except Exception as e:
            self.search_ctrl.Clear()
            self.load_directory(self.current_directory)
            raise Exception(f"Failed to rename {filepath}: {str(e)}")
    
    def on_move_files(self, event):
        """Move selected files to a different directory."""
        # Check if any files are selected
        selected_items = []
        item = self.file_list.GetFirstSelected()
        
        while item != -1:
            selected_items.append(item)
            item = self.file_list.GetNextSelected(item)
        
        if not selected_items:
            wx.MessageBox("No files selected for moving.", "No Selection", wx.OK | wx.ICON_INFORMATION)
            return
        
        # Ask user for the destination directory
        with wx.DirDialog(self, "Choose destination directory",
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return  # User canceled
            destination = dlg.GetPath()
        
        # Move the selected files
        successful_moves = 0
        failed_moves = []
        
        for item in selected_items:
            file_name = self.file_list.GetItemText(item)
            source_path = os.path.join(self.current_directory, file_name)
            dest_path = os.path.join(destination, file_name)
            
            try:
                # Check if destination file already exists
                if os.path.exists(dest_path):
                    dlg = wx.MessageDialog(self, 
                                          f"File '{file_name}' already exists in destination. Overwrite?",
                                          "File Exists",
                                          wx.YES_NO | wx.ICON_QUESTION)
                    if dlg.ShowModal() == wx.ID_YES:
                        shutil.move(source_path, dest_path)
                        successful_moves += 1
                    else:
                        failed_moves.append(f"{file_name} (skipped)")
                    dlg.Destroy()
                else:
                    shutil.move(source_path, dest_path)
                    successful_moves += 1
            except Exception as e:
                failed_moves.append(f"{file_name} ({str(e)})")
        
        # Update the file list
        self.update_file_list()
        
        # Show results to user
        if failed_moves:
            message = f"Moved {successful_moves} file(s) successfully.\n\nThe following files could not be moved:\n" + "\n".join(failed_moves)
            wx.MessageBox(message, "Move Results", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(f"Successfully moved {successful_moves} file(s).", "Move Complete", wx.OK | wx.ICON_INFORMATION)

    def update_file_list(self):
        selected_path = self.dir_path.GetPath()
        self.load_directory(selected_path)

    def on_delete_files(self, event):
        """Delete selected files."""
        selected_items = []
        item = self.file_list.GetFirstSelected()
        
        while item != -1:
            selected_items.append(item)
            item = self.file_list.GetNextSelected(item)
        
        if not selected_items:
            wx.MessageBox("No files selected for deletion.", "No Selection", wx.OK | wx.ICON_INFORMATION)
            return
        
        # Get file names for display in confirmation dialog
        file_names = [self.file_list.GetItemText(item) for item in selected_items]
        
        # Confirmation dialog
        files_str = "\n".join(file_names[:10])
        if len(file_names) > 10:
            files_str += f"\n... and {len(file_names) - 10} more file(s)"
        
        msg = f"Are you sure you want to delete the following file(s)?\n\n{files_str}\n\nThis action cannot be undone."
        dlg = wx.MessageDialog(self, msg, "Confirm Deletion", 
                              wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
        
        if dlg.ShowModal() == wx.ID_YES:
            # User confirmed deletion
            successful_deletes = 0
            failed_deletes = []
            
            for item in selected_items:
                file_name = self.file_list.GetItemText(item)
                file_path = os.path.join(self.current_directory, file_name)
                
                try:
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)  # Delete directory and its contents
                    else:
                        os.remove(file_path)  # Delete file
                    successful_deletes += 1
                except Exception as e:
                    failed_deletes.append(f"{file_name} ({str(e)})")
            
            # Update the file list
            self.update_file_list()
            
            # Show results to user
            if failed_deletes:
                message = f"Deleted {successful_deletes} file(s) successfully.\n\nThe following files could not be deleted:\n" + "\n".join(failed_deletes)
                wx.MessageBox(message, "Deletion Results", wx.OK | wx.ICON_INFORMATION)
            else:
                wx.MessageBox(f"Successfully deleted {successful_deletes} file(s).", "Deletion Complete", wx.OK | wx.ICON_INFORMATION)
        
        dlg.Destroy()

    def download_files(self, download_tasks):
        total_files = len(download_tasks)
        progress_dialog = wx.ProgressDialog(
            "Downloading Files",
            "Preparing to download...",
            maximum=total_files,
            parent=self,
            style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL
        )

        downloaded_files = []
        errors = []

        try:
            with Pool(processes=10) as pool:
                for i, result in enumerate(pool.imap_unordered(download_reps_worker, download_tasks)):
                    index, status = result
                    filename = self.file_list.GetItemText(index)
                    rep_url = self.file_list.GetItem(index, 4).GetText()

                    if status == 'done':
                        downloaded_files.append(rep_url)
                        progress_dialog.Update(i + 1, f"Downloaded {filename} ({i+1}/{total_files})")
                    else:
                        errors.append((rep_url, status))
                        progress_dialog.Update(i + 1, f"Error: {filename} ({i+1}/{total_files})")

                    wx.Yield()

            progress_dialog.Destroy()
            self.search_ctrl.Clear()
            for index in range(self.file_list.GetItemCount()):
                check_rep_url = self.file_list.GetItem(index, 4).GetText()
                if check_rep_url in downloaded_files:
                    self.file_list.Select(index)
                    self.file_list.Focus(index)

            if errors:
                error_text = "\n".join(f"{f}: {msg}" for f, msg in errors)
                wx.MessageBox(f"{len(downloaded_files)} downloaded, {len(errors)} failed:\n\n{error_text}", "Partial Success", wx.OK | wx.ICON_WARNING)
            else:
                wx.MessageBox(f"{total_files} file(s) downloaded successfully!", "Success", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            progress_dialog.Destroy()
            wx.MessageBox(f"Error downloading files: {e}", "Error", wx.OK | wx.ICON_ERROR)
    
    def get_user_id_date_from_url(self, url):
        try:
            url_dir, file_name = url.rsplit('/', 1)
            url_dir, user_id = url_dir.rsplit('_', 1)
            _, year_month, day, _ = url_dir.rsplit('/', 3)
            return f"{user_id}_{year_month[:4]}-{year_month[5:7]}-{day[:2]}"
        except:
            return ""

    def on_download_file(self):
        selected_indices = []

        index = self.file_list.GetFirstSelected()
        while index != -1:
            selected_indices.append(index)
            index = self.file_list.GetNextSelected(index)

        if not selected_indices:
            return

        dialog = wx.DirDialog(self, "Choose a directory to save the files", style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return

        save_dir = dialog.GetPath()
        dialog.Destroy()

        download_tasks = []

        for index in selected_indices:
            file_url = self.file_list.GetItem(index, 4).GetText()
            filename = self.file_list.GetItemText(index)
            save_path = os.path.join(save_dir, f"{self.get_user_id_date_from_url(file_url)}_{filename}")
            download_tasks.append((index, file_url, save_path))

        self.download_files(download_tasks)
    
    def on_download_all_files(self):
        dialog = wx.DirDialog(self, "Choose a directory to save the files", style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return

        save_dir = dialog.GetPath()
        dialog.Destroy()

        item_count = self.file_list.GetItemCount()
        if item_count == 0:
            wx.MessageBox("No files to download.", "Info", wx.OK | wx.ICON_INFORMATION)
            return

        download_tasks = []
        for index in range(item_count):
            file_url = self.file_list.GetItem(index, 4).GetText()
            filename = self.file_list.GetItemText(index)
            save_path = os.path.join(save_dir, f"{self.get_user_id_date_from_url(file_url)}_{filename}")
            download_tasks.append((index, file_url, save_path))

        self.download_files(download_tasks)

    def setup_online_controls(self):

        # Date range selection
        date_hbox = wx.BoxSizer(wx.HORIZONTAL)
        address_label = wx.StaticText(self, label="Gentool Directory:")
        date_hbox.Add(address_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=3)
        self.url_ctrl = wx.TextCtrl(self, style=wx.TE_READONLY)  # Read-only display
        self.update_address_display()
        date_hbox.Add(self.url_ctrl, proportion=1, flag=wx.EXPAND| wx.RIGHT, border=3)

        # use UTC time
        today = datetime.now(timezone.utc).date()
        lower_bound = today - timedelta(days=71)
        wx_today = wx.DateTime().Set(today.day, today.month - 1, today.year)
        wx_lower_bound = wx.DateTime.FromDMY(lower_bound.day, lower_bound.month - 1, lower_bound.year)

        date_hbox.Add(wx.StaticText(self, label="Start Date:"), flag=wx.ALIGN_CENTER_VERTICAL)
        self.start_date = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN)
        self.start_date.SetRange(wx_lower_bound, wx_today)
        date_hbox.Add(self.start_date, proportion=0, flag=wx.EXPAND | wx.LEFT, border=5)
        
        date_hbox.Add(wx.StaticText(self, label="End Date:"), flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=5)
        self.end_date = wx.adv.DatePickerCtrl(self, style=wx.adv.DP_DROPDOWN)
        self.end_date.SetRange(wx_lower_bound, wx_today)
        date_hbox.Add(self.end_date, proportion=0, flag=wx.EXPAND | wx.LEFT, border=5)


        # Browse directories button
        self.browse_btn = wx.Button(self, label="Browse")
        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_directories)
        date_hbox.Add(self.browse_btn, flag=wx.LEFT, border=5)
        
        self.GetSizer().Insert(1, date_hbox, flag=wx.EXPAND | wx.ALL, border=5)

    def update_address_display(self):
        """Update the address bar with current directories"""
        if self.current_directories:
            dirs = ";".join(self.current_directories)
            self.url_ctrl.SetValue(dirs)
        else:
            self.url_ctrl.SetValue("No directories selected. Click Browse to select.")

    def on_browse_directories(self, event):                                                       
        if self.start_date.GetValue() > self.end_date.GetValue():
            wx.MessageBox(
                "Start date must be a valid date before or the same as the end date.",
                "Invalid Date Range",
                wx.OK | wx.ICON_ERROR
            )
            return
        
        dlg = DirectorySelectionDialog(
            self,
            start_date = self.start_date.GetValue().Format("%Y-%m-%d"),
            end_date = self.end_date.GetValue().Format("%Y-%m-%d")
        )
        
        if dlg.ShowModal() == wx.ID_OK:
            self.current_directories = dlg.get_selected_directories()
            self.update_address_display()
        else:
            self.current_directories = dlg.current_directories
        dlg.Destroy()
        
        if self.current_directories:
            self.directories_to_fetch = dlg.get_directories_to_fetch()
            self.load_multiple_directories(self.directories_to_fetch)
        
        # Explicitly bring main window back to front after dialog closes
        self.Raise()
        self.file_list.SetFocus()
          
        # Extra assurance for focus on Windows
        if wx.Platform == '__WXMSW__':
            self.SetFocus()
            self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
            self.SetWindowStyle(self.GetWindowStyle() & ~wx.STAY_ON_TOP)

    def load_multiple_directories(self, directories_to_fetch):
        """Load files from multiple selected directories"""
        self.all_files = self.run_in_pool(get_dir_files_worker, directories_to_fetch)    
        # Display combined files
        self.all_files.sort(key=lambda item: item[2])
        self.display_files(self.all_files)

    def display_files(self, files):
        """Display files in the list control"""
        self.file_list.DeleteAllItems()
        self.action_all_btn.Enable()
        for name, size, date, gt_dir, file_url in files:
            icon = self.file_list.rep_file_idx if name.lower().endswith('.rep') else self.file_list.file_idx
            idx = self.file_list.InsertItem(self.file_list.GetItemCount(), name, icon)
            self.file_list.SetItem(idx, 1, str(size))
            self.file_list.SetItem(idx, 2, date)
            self.file_list.SetItem(idx, 3, gt_dir)
            self.file_list.SetItem(idx, 4, file_url)
            self.file_list.SetItemData(idx, 2)
        self.file_count_label.SetLabel(f"Found: {len(files)} replays")
    
    def run_in_pool(self, func, urls_to_process):    
        with wx.ProgressDialog(
            "Fetching data",
            "Fetching...",
            maximum=len(urls_to_process),
            parent=self,
            style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL
        ) as dlg:
            success_files = []
            error_404 = []
            error_others = []
            try:
                with Pool(processes=10) as pool:
                    for idx, result in enumerate(pool.imap_unordered(func, urls_to_process)):
                        success, err_404, err_other = result
                        if success:
                            success_files.extend(success)
                            dlg.Update(idx + 1, f"{success[0]} ({idx+1}/{len(urls_to_process)})")
                        elif err_404:
                            error_404.append(err_404)
                            dlg.Update(idx + 1, f"{err_404} ({idx+1}/{len(urls_to_process)})")
                        elif err_other:
                            error_others.append(err_other)
                            dlg.Update(idx + 1, f"{err_other} ({idx+1}/{len(urls_to_process)})")
                        wx.Yield()

            except Exception as e:
                wx.MessageBox(f"An error occurred: {e}", "Error", wx.OK | wx.ICON_ERROR)
                return
            error_404.sort()
            error_others.sort()
            if error_404:
                wx.MessageBox(
                    f"No data found (404) for:\n{chr(10).join(error_404)}",
                    "Not Found", wx.OK | wx.ICON_WARNING
                )
            if error_others:
                wx.MessageBox(
                    f"Failed to fetch data:\n\n{chr(10).join(error_others)}",
                    "Error", wx.OK | wx.ICON_ERROR
                )
            return success_files

class DirectorySelectionDialog(wx.Dialog):
    def __init__(self, parent, start_date, end_date):
        super().__init__(parent, title="Choose User Directories", 
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        # Initialize
        # self.base_url = base_url
        self.start_date = start_date
        self.end_date = end_date
        self.all_directories = []
        self.selected_directories = []
        self.current_directories = []
        
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        days_diff = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1
        # Date range info
        date_info = wx.StaticText(self, label=f"Date Range: {start_date} to {end_date} ({days_diff} days)")
        vbox.Add(date_info, flag=wx.EXPAND | wx.ALL, border=5)
        
        # Search controls
        search_hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        search_hbox.Add(self.search_ctrl, proportion=1, flag=wx.EXPAND)
        
        self.search_btn = wx.Button(self, label="Search")
        self.search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        search_hbox.Add(self.search_btn, flag=wx.LEFT, border=5)
        vbox.Add(search_hbox, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=5)
        
        info_vbox = wx.BoxSizer(wx.VERTICAL)

        # Add count label
        self.count_label = wx.StaticText(self, label="Found: 0")
        info_vbox.Add(self.count_label, flag=wx.TOP | wx.RIGHT, border=5)

        # Add selection label below the count label
        self.selection_label = wx.StaticText(self, label="Selected: 0")
        info_vbox.Add(self.selection_label, flag=wx.TOP | wx.RIGHT, border=5)

        # Add the info_vbox to your main vbox
        vbox.Add(info_vbox, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)


        # Multi-select results list
        self.results_list = SortableListCtrl(
            self, 
            columns=[("User Directory", 250), ("Days Found", 100)],
            style=wx.LC_REPORT | wx.BORDER_SUNKEN
        )
        
        self.results_list.Bind(wx.EVT_LEFT_DOWN, self.on_left_click)
        
        vbox.Add(self.results_list, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)
        
        # Create a container sizer for all bottom buttons
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Left side: Select All and Invert buttons
        left_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.select_all_btn = wx.Button(self, label="Select All")
        self.select_all_btn.Bind(wx.EVT_BUTTON, self.on_select_all)
        left_btn_sizer.Add(self.select_all_btn, flag=wx.RIGHT, border=5)

        self.invert_btn = wx.Button(self, label="Invert Selection")
        self.invert_btn.Bind(wx.EVT_BUTTON, self.on_invert_selection)
        left_btn_sizer.Add(self.invert_btn)
        
        bottom_sizer.Add(left_btn_sizer, flag=wx.ALIGN_CENTER_VERTICAL)
        bottom_sizer.AddStretchSpacer()

        # Right side: Standard OK/Cancel buttons
        btn_sizer = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(self, wx.ID_OK, "Process Selected")
        self.ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        btn_sizer.AddButton(self.ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL))
        btn_sizer.Realize()

        bottom_sizer.Add(btn_sizer, flag=wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(bottom_sizer, flag=wx.EXPAND|wx.ALL, border=5)

        self.SetSizerAndFit(vbox)
        self.SetSize(450, 500)
        self.Center()
        self.search_ctrl.SetFocus()

        # Initialize database connection
        self.db = UserDirectoryDB()  # Our database helper class
        self.check_database_and_load()

    def on_left_click(self, event):
        """Toggle selection on left click"""
        pos = event.GetPosition()
        index, flags = self.results_list.HitTest(pos)
        if index != -1 and flags & wx.LIST_HITTEST_ONITEM:
            self.results_list.Select(index, not self.results_list.IsSelected(index))
            self.results_list.Focus(index)
            self.results_list.SetFocus()
            self.update_selection_count()

    def update_selection_count(self):
        """Display the number of selected items"""
        selected_count = self.results_list.GetSelectedItemCount()
        selected_indices = []
        index = self.results_list.GetFirstSelected()
        while index != -1:
            selected_indices.append(index)
            index = self.results_list.GetNextSelected(index)
        self.selection_label.SetLabel(f"Selected: {selected_count}")
        self.ok_btn.Enable(selected_count > 0)

    def on_select_all(self, event):
        """Select all items"""
        for i in range(self.results_list.GetItemCount()):
            self.results_list.Select(i, True)
        self.results_list.SetFocus()
        self.update_selection_count()

    def on_invert_selection(self, event):
        """Invert selection states"""
        for i in range(self.results_list.GetItemCount()):
            self.results_list.Select(i, not self.results_list.IsSelected(i))
        self.results_list.SetFocus()
        self.update_selection_count()

    def get_selected_directories(self):
        """Return list of selected directory names"""
        selected = []
        index = self.results_list.GetFirstSelected()
        while index != -1:
            selected.append(self.results_list.GetItemText(index))
            index = self.results_list.GetNextSelected(index)
        self.current_directories = selected[:]
        return selected

    def get_directories_to_fetch(self):
        return self.db.get_directory_dates_for_range(self.selected_directories, self.start_date, self.end_date)


    def on_ok(self, event):
        """Handle OK button - return checked directories"""
        self.selected_directories = self.get_selected_directories()
        if not self.selected_directories:
            wx.MessageBox("Please select at least one directory", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        self.EndModal(wx.ID_OK)

    def populate_results(self):
        """Update results list and enable multi-selection"""
        self.results_list.DeleteAllItems()
        # self.all_directories = directories
        
        for user_dir, count in self.all_directories:
            idx = self.results_list.InsertItem(self.results_list.GetItemCount(), user_dir)
            self.results_list.SetItem(idx, 1, str(count))
        
        self.count_label.SetLabel(f"Found: {len(self.all_directories)}")
        self.selection_label.SetLabel("Selected: 0")
        self.ok_btn.Enable(False)  # Disabled until selections are made

    def on_search(self, event):
        """Handle search button or Enter key"""
        query = self.search_ctrl.GetValue().strip()
        
        if not query:
            wx.MessageBox("Please enter a search term", "Info", wx.OK | wx.ICON_INFORMATION)
            return
        
        with wx.BusyCursor():
            self.all_directories = self.query_directories(query)
            self.populate_results()

    def query_directories(self, query=None):
        """Query database with optional filter"""
        if query:
            return self.db.search_users(self.start_date, self.end_date, query)
        # return self.db.query_users(self.start_date, self.end_date)
    
    def check_database_and_load(self):
        with wx.ProgressDialog("Loading", "Checking database...", 
                               parent=self, style=wx.PD_APP_MODAL) as pd:
            try:
                pd.Pulse("Verifying database...")
                missing_dates = self.database_exists()
                
                if missing_dates:
                    missing_dates = [d.strftime('%Y-%m-%d') for d in missing_dates]
                    msg = "Database needs to update the directories for the following dates:\n"
                    msg += "\n".join(missing_dates[:5])
                    if len(missing_dates) > 5:
                        msg += f"\n...and {len(missing_dates)-5} more"
            except Exception as e:
                wx.MessageBox(f"Error: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
                return False
        if missing_dates:
            confirm = wx.MessageBox(
                f"{msg}\n\nUpdate database now?",
                "Database Update Needed",
                wx.YES_NO | wx.ICON_QUESTION
            )
            
            if confirm != wx.YES:
                return False
            
            with wx.ProgressDialog("Updating", "Updating database...", 
                                  parent=self, style=wx.PD_APP_MODAL) as update_pd:
                try:
                    self.update_database()
                except Exception as e:
                    wx.MessageBox(f"Error during update: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)
                    return False
    
    def database_exists(self):
        """Check if we have data for this date range"""
        return self.db.has_data_for_range(self.start_date, self.end_date)

    def update_database(self):
        """Fetch data and update database"""
        self.db.update_for_date_range(
            start_date=self.start_date,
            end_date=self.end_date
        )

class UserDirectoryDB:
    def __init__(self):
        self.conn = sqlite3.connect("player_directories.db")
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.dates_to_update = []

    def create_tables(self):
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS directories (
            user_id TEXT,
            date TEXT,
            PRIMARY KEY (user_id, date)
        )""")
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS status (
            date TEXT CHECK(length(date) = 10) PRIMARY KEY,
            is_complete INTEGER CHECK(is_complete IN (0, 1))
        )
        ''')
        self.conn.commit()

    def get_dates_between(self, start_date, end_date):
        delta = end_date - start_date
        return [start_date + timedelta(days=i) for i in range(delta.days + 1)]

    def has_data_for_range(self, start_date, end_date):

        # First delete any directory data 70 days older than today.
        last_day = datetime.now(timezone.utc).date() - timedelta(days=71)
        self.cursor.execute("DELETE FROM directories WHERE date < ?", (last_day.isoformat(),))
        self.conn.commit()
        
        date_list = self.get_dates_between(date.fromisoformat(start_date), date.fromisoformat(end_date))
        date_strs = [d.isoformat() for d in date_list]
        placeholders = ','.join('?' for _ in date_strs)
        query = f"SELECT date, is_complete FROM status WHERE date IN ({placeholders})"
        self.cursor.execute(query, date_strs)
        results = self.cursor.fetchall()
        completed_dates = {row[0] for row in results if row[1] == 1}
        dates_to_process = [d for d in date_strs if d not in completed_dates]
        self.dates_to_update = [date.fromisoformat(s) for s in dates_to_process]

        return self.dates_to_update

    def update_for_date_range(self, start_date, end_date):
        temp_folder_path = os.path.join(os.getcwd(), "temp")

        try:
            os.makedirs(temp_folder_path, exist_ok=True)
        except OSError as e:
            print(f"Error creating temporary folder: {e}")

        base_url = "https://gentool.net/data/zh"
        urls_to_process = []
        for d in self.dates_to_update:
            full_url = f"{base_url}/{d.strftime("%Y_%m_%B/%d_%A")}/"
            urls_to_process.append((full_url, d))

        success_files = run_in_pool(get_directories_worker, urls_to_process)

        if success_files:
            for given_date in success_files:
                today_str = datetime.now(timezone.utc).date().isoformat()                
                file_path = os.path.join(temp_folder_path, f"{given_date}.txt")
                try:
                    with open(file_path, 'r') as file:
                        directories = [line.strip() for line in file if line.strip()]

                    batch_data = [(directory, given_date) for directory in directories]
                    
                    self.cursor.execute("SELECT is_complete FROM status WHERE date = ?", (given_date,))
                    row = self.cursor.fetchone()
                    if given_date == today_str:
                        if row is None:
                            self.cursor.execute("INSERT INTO status (date, is_complete) VALUES (?, ?)", (given_date, 0))
                        elif row[0] == 0:
                            self.cursor.execute("DELETE FROM directories WHERE date = ?", (given_date,))
                        self.cursor.executemany(
                            "INSERT INTO directories (user_id, date) VALUES (?, ?)",
                            batch_data
                        )
                    elif given_date < today_str:
                        if row is None:
                            self.cursor.execute("INSERT INTO status (date, is_complete) VALUES (?, ?)", (given_date, 1))
                        elif row[0] == 0:
                            self.cursor.execute("DELETE FROM directories WHERE date = ?", (given_date,))
                            self.cursor.execute("UPDATE status SET is_complete = ? WHERE date = ?", (1, given_date))
                        if row is None or row[0] == 0:    
                            self.cursor.executemany(
                                "INSERT INTO directories (user_id, date) VALUES (?, ?)",
                                batch_data
                            )
                    os.remove(file_path)
                    
                except ValueError as e:
                    print(f"Error parsing date from filename {file_path}: {e}")
                except Exception as e:
                    print(f"Error processing file {file_path}: {e}")
            self.conn.commit()

    def search_users(self, start_date, end_date, query):
        """Search users with name matching query"""
        query = query.split()
        results = []
        for uid in query:
            query = """
                SELECT user_id, COUNT(*) as days
                FROM directories
                WHERE date BETWEEN ? AND ?
                AND user_id LIKE ?
                GROUP BY user_id
                ORDER BY days DESC
            """
            self.cursor.execute(query, (start_date, end_date, f"%{uid}%"))
            results.extend(self.cursor.fetchall())

        return results

    def get_directory_dates_for_range(self, user_dirs, start_date, end_date):
        dates_to_process = []
        for udir in user_dirs:
            self.cursor.execute("""
                SELECT user_id, date
                FROM directories
                WHERE user_id = ?
                  AND date BETWEEN ? AND ?
                ORDER BY date
            """, (udir, start_date, end_date))

            dates_to_process.extend([(row[0], datetime.strptime(row[1], "%Y-%m-%d")) for row in self.cursor.fetchall()])

        base_url = "https://gentool.net/data/zh"
        urls_to_check = []
        for udir, d in dates_to_process:
            full_url = f"{base_url}/{d.strftime("%Y_%m_%B/%d_%A")}/{quote(udir)}"
            urls_to_check.append((full_url, udir, d))
        return urls_to_check


def get_directories_worker(urls_to_process):
    file_url, url_date = urls_to_process
    formatted_date_path = url_date.strftime('%Y_%m_%B/%d_%A')
    try:
        response = requests.get(file_url)
        if response.status_code != 200:
            return ([], formatted_date_path if response.status_code == 404 else '', 
                   '' if response.status_code == 404 else formatted_date_path)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = [a.get_text(strip=True) for a in soup.select('td a')]
        
        if links and len(links) > 1:
            temp_dir = os.path.join(os.getcwd(), "temp")
            os.makedirs(temp_dir, exist_ok=True)
            date_string = url_date.strftime('%Y-%m-%d')
            file_path = os.path.join(temp_dir, f"{date_string}.txt")
            with open(file_path, 'w') as file:
                file.writelines(f"{item}\n" for item in links[1:])
            return ([date_string], '', '')
        else:
            return ([], '', formatted_date_path)
            
    except requests.RequestException:
        return ([], '', formatted_date_path)
    except Exception:
        return ([], '', formatted_date_path)

def get_dir_files_worker(urls_to_process):
    dir_url, user_dir, url_date = urls_to_process
    files_list = []
    formatted_date_path = url_date.strftime('%Y_%m_%B/%d_%A')

    try:
        response = requests.get(dir_url)
        if response.status_code != 200:
            return (files_list, formatted_date_path if response.status_code == 404 else '', 
                   '' if response.status_code == 404 else formatted_date_path)

        if dir_url[-1] != '/':
            dir_url += '/'
        
        doc = BeautifulSoup(response.content, "lxml")
        rows = doc.find_all('tr')

        for row in rows:
            tds = row.find_all('td')
            if len(tds) < 2:
                continue
            last_td_text = row.find_all('td')[-1].text.strip()
            if last_td_text == 'Replay':
                file_name = row.find('a').text
                file_url = row.find('a')['href']
                date_time = row.find_all('td')[2].text.strip()
                file_size = row.find_all('td')[3].text.strip()
                divisor = 1024
                if 'K' in file_size:
                    divisor = 1
                elif 'M' in file_size:
                    divisor = 1/1024
                file_size_numeric = float(re.sub(r'[^\d.]', '', file_size))/divisor
                
                files_list.append([file_name, file_size_numeric, date_time, user_dir, f"{dir_url}{file_name}"])
        return (files_list, '', '')
    except Exception as e:
        return (files_list, '', formatted_date_path)

def download_reps_worker(args):
    index, file_url, save_path = args
    try:
        response = requests.get(file_url)
        # response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return (index, 'done')
    except Exception as e:
        return (index, f'error:{str(e)}')

def run_in_pool(func, urls_to_process):    
    with wx.ProgressDialog(
        "Fetching data",
        "Fetching...",
        maximum=len(urls_to_process),
        style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL
    ) as dlg:
        success_files = []
        error_404 = []
        error_others = []
        try:
            with Pool(processes=10) as pool:
                for idx, result in enumerate(pool.imap_unordered(func, urls_to_process)):
                    success, err_404, err_other = result
                    if success:
                        success_files.extend(success)
                        dlg.Update(idx + 1, f"{success[0]} ({idx+1}/{len(urls_to_process)})")
                    elif err_404:
                        error_404.append(err_404)
                        dlg.Update(idx + 1, f"{err_404} ({idx+1}/{len(urls_to_process)})")
                    elif err_other:
                        error_others.append(err_other)
                        dlg.Update(idx + 1, f"{err_other} ({idx+1}/{len(urls_to_process)})")
                    wx.Yield()

        except Exception as e:
            wx.MessageBox(f"An error occurred: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return
        error_404.sort()
        error_others.sort()
        if error_404:
            wx.MessageBox(
                f"No data found (404) for:\n{chr(10).join(error_404)}",
                "Not Found", wx.OK | wx.ICON_WARNING
            )
        if error_others:
            wx.MessageBox(
                f"Failed to fetch data:\n\n{chr(10).join(error_others)}",
                "Error", wx.OK | wx.ICON_ERROR
            )
        return success_files

class MyFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(MyFrame, self).__init__(*args, **kw)
        self.notebook = wx.Notebook(self)
        
        self.tab1 = ReplayBrowserTab(self.notebook, "local")
        self.tab2 = ReplayBrowserTab(self.notebook, "online")
        
        self.notebook.AddPage(self.tab1, "Local Replays")
        self.notebook.AddPage(self.tab2, "Gentool Replays")
        
        self.SetSize(1300, 700)
        self.SetTitle("Replay Info v1.1")
        self.Centre()
        self.Show(True)

class ReplayViewer(wx.App):
    def OnInit(self):
        self.frame = MyFrame(None)
        return True
