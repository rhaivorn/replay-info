import wx
import os
import datetime
import requests
from urllib.parse import urljoin
import replay_result
import re
import requests
from bs4 import BeautifulSoup
import threading


class MyFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(MyFrame, self).__init__(*args, **kw)

        # Create a notebook (tabs holder)
        self.notebook = wx.Notebook(self)

        # Create the first tab
        self.tab1 = wx.Panel(self.notebook)
        self.notebook.AddPage(self.tab1, "Local Replays")

        # Create the second tab
        self.tab2 = wx.Panel(self.notebook)
        self.notebook.AddPage(self.tab2, "Gentool Replays")

        # Add content to the first tab
        self.setup_tab1()

        # Add content to the second tab
        self.setup_tab2()

        # Set the frame size and show it
        self.SetSize(1300, 700)
        self.SetTitle("Replay Info v1.0 by Rhaivorn")
        self.Centre()
        self.Show(True)


    def setup_tab1(self):
        # Create a vertical box sizer for the first tab
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Address bar (spans the entire width of the GUI)
        address_hbox = wx.BoxSizer(wx.HORIZONTAL)
        address_label = wx.StaticText(self.tab1, label="Local Directory:")
        address_hbox.Add(address_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=2)
        self.dir_path = wx.TextCtrl(self.tab1, style=wx.TE_READONLY)
        address_hbox.Add(self.dir_path, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)
        select_dir_btn = wx.Button(self.tab1, label="Select Directory")
        select_dir_btn.Bind(wx.EVT_BUTTON, self.on_select_directory)
        address_hbox.Add(select_dir_btn, proportion=0, flag=wx.ALL, border=2)

        # Add the address bar to the top of the vertical sizer
        vbox.Add(address_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)

        # Create a splitter window for the left and right sections
        self.splitter = wx.SplitterWindow(self.tab1, style=wx.SP_LIVE_UPDATE)
        self.splitter.SetMinimumPaneSize(100)  # Set a minimum size for each pane
        color = self.tab1.GetBackgroundColour()
        self.splitter.SetBackgroundColour(color)
        # Left side: Directory selection, search bar, and file list
        left_panel = wx.Panel(self.splitter)
        left_vbox = wx.BoxSizer(wx.VERTICAL)

        # Search bar
        self.search_ctrl = wx.SearchCtrl(left_panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetDescriptiveText("Search files...")
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search)
        self.search_ctrl.Bind(wx.EVT_SEARCH_CANCEL, self.on_search_cancel)
        left_vbox.Add(self.search_ctrl, proportion=0, flag=wx.EXPAND | wx.LEFT | wx.BOTTOM, border=2)

        # File list
        self.file_list = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.file_list.InsertColumn(0, "Filename", width=200)
        self.file_list.InsertColumn(1, "File Size (KB)", width=50)
        self.file_list.InsertColumn(2, "Date Modified", width=150)
        self.file_list.SetMinSize((300, -1))  # Set width to 200 pixels, height to default
        self.file_list.Bind(wx.EVT_LIST_COL_CLICK, self.on_column_click)
        self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_file_selected)
        self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_file_deselected)
        left_vbox.Add(self.file_list, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.TOP | wx.BOTTOM, border=2)

        # Rename buttons
        rename_buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.rename_file_btn = wx.Button(left_panel, label="Rename File")
        self.rename_file_btn.Bind(wx.EVT_BUTTON, self.on_rename_file)
        self.rename_file_btn.Disable()  # Disable by default
        rename_buttons_hbox.Add(self.rename_file_btn, proportion=0, flag=wx.ALL, border=2)

        self.rename_all_files_btn = wx.Button(left_panel, label="Rename All Files")
        self.rename_all_files_btn.Bind(wx.EVT_BUTTON, self.on_rename_all_files)
        self.rename_all_files_btn.Disable()  # Disable by default
        rename_buttons_hbox.Add(self.rename_all_files_btn, proportion=0, flag=wx.ALL, border=2)

        left_vbox.Add(rename_buttons_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)

        # Set the sizer for the left panel
        left_panel.SetSizer(left_vbox)

        # Right side: File properties and Player info
        right_panel = wx.Panel(self.splitter)
        right_vbox = wx.BoxSizer(wx.VERTICAL)

        # Address bar for the right side (if needed, otherwise remove this)
        # right_address_hbox = wx.BoxSizer(wx.HORIZONTAL)
        # right_address_label = wx.StaticText(right_panel, label="Selected File:")
        # right_address_hbox.Add(right_address_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=2)
        # self.selected_file_path = wx.TextCtrl(right_panel, style=wx.TE_READONLY)
        self.selected_file_path = ""
        # right_address_hbox.Add(self.selected_file_path, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)
        # right_vbox.Add(right_address_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)

        # Create a splitter for the File Properties and Player info sections
        self.right_splitter = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        self.right_splitter.SetMinimumPaneSize(50)  # Set a minimum size for each pane

        # File properties section (top pane)
        properties_panel = wx.Panel(self.right_splitter)
        # properties_box = wx.StaticBox(properties_panel, label="File Properties")
        # properties_sizer = wx.StaticBoxSizer(properties_box, wx.VERTICAL)
        properties_sizer = wx.BoxSizer(wx.VERTICAL)
        self.properties_list = wx.ListCtrl(properties_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.properties_list.InsertColumn(0, "Property", width=150)
        self.properties_list.InsertColumn(1, "Value", width=400)
        properties_sizer.Add(self.properties_list, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        properties_panel.SetSizer(properties_sizer)

        # Player info section (bottom pane)
        player_info_panel = wx.Panel(self.right_splitter)
        # dummy_box = wx.StaticBox(player_info_panel, label="Player info")
        # player_info_sizer = wx.StaticBoxSizer(dummy_box, wx.VERTICAL)
        player_info_sizer = wx.BoxSizer(wx.VERTICAL)
        self.details_list = wx.ListCtrl(player_info_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.details_list.InsertColumn(0, 'Team', width=50)
        self.details_list.InsertColumn(1, 'Hex IP', width=80)
        self.details_list.InsertColumn(2, 'Player Names', width=100)
        self.details_list.InsertColumn(3, 'Faction', width=200)
        self.details_list.InsertColumn(4, 'Surrender/Exit?', width=80)
        self.details_list.InsertColumn(5, 'Surrender', width=80)
        self.details_list.InsertColumn(6, 'Exit', width=80)
        self.details_list.InsertColumn(7, 'Idle/Kicked?', width=80)
        self.details_list.InsertColumn(8, 'Last CRC', width=80)
        self.details_list.InsertColumn(9, 'Placement', width=50)
        player_info_sizer.Add(self.details_list, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        player_info_panel.SetSizer(player_info_sizer)

        # Split the right section vertically
        self.right_splitter.SplitHorizontally(properties_panel, player_info_panel, sashPosition=350)  # Initial sash position

        # Add the right splitter to the right panel's sizer
        right_vbox.Add(self.right_splitter, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)

        # Set the sizer for the right panel
        right_panel.SetSizer(right_vbox)

        # Split the main window vertically
        self.splitter.SplitVertically(left_panel, right_panel, sashPosition=350)  # Initial sash position

        # Add the splitter to the vertical sizer
        vbox.Add(self.splitter, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)

        # Set the sizer for the first tab
        self.tab1.SetSizer(vbox)

        # Track the current sort column and order
        self.sort_column = -1  # No column sorted initially
        self.sort_ascending = True  # Default to ascending order

        # Store the full list of files for filtering
        self.full_file_list = []

        if self.dir_path.GetValue() == '':
            self.update_file_list(os.path.join(os.environ['USERPROFILE'], 'Documents\\Command and Conquer Generals Zero Hour Data\\Replays'))
            self.dir_path.SetValue(os.path.join(os.environ['USERPROFILE'], 'Documents\\Command and Conquer Generals Zero Hour Data\\Replays'))
            self.rename_all_files_btn.Enable()
    

    def setup_tab2(self):
        # Create a vertical box sizer for the second tab
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Address bar (spans the entire width of the GUI)
        address_hbox = wx.BoxSizer(wx.HORIZONTAL)
        address_label = wx.StaticText(self.tab2, label="Gentool Directory:")
        address_hbox.Add(address_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=2)
        self.online_address = wx.TextCtrl(self.tab2)
        address_hbox.Add(self.online_address, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)
        fetch_files_btn = wx.Button(self.tab2, label="Fetch Files")
        fetch_files_btn.Bind(wx.EVT_BUTTON, self.on_fetch_files)
        address_hbox.Add(fetch_files_btn, proportion=0, flag=wx.ALL, border=2)

        # Add the address bar to the top of the vertical sizer
        vbox.Add(address_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)

        # Create a splitter window for the left and right sections
        self.splitter_tab2 = wx.SplitterWindow(self.tab2, style=wx.SP_LIVE_UPDATE)
        self.splitter_tab2.SetMinimumPaneSize(100)  # Set a minimum size for each pane


        color = self.tab2.GetBackgroundColour()
        self.splitter_tab2.SetBackgroundColour(color)

        # Left side: Search bar and file list
        left_panel = wx.Panel(self.splitter_tab2)
        left_vbox = wx.BoxSizer(wx.VERTICAL)

        # Search bar
        self.search_ctrl_tab2 = wx.SearchCtrl(left_panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl_tab2.SetDescriptiveText("Search files...")
        self.search_ctrl_tab2.Bind(wx.EVT_TEXT, self.on_search_tab2)
        self.search_ctrl_tab2.Bind(wx.EVT_SEARCH_CANCEL, self.on_search_cancel_tab2)
        left_vbox.Add(self.search_ctrl_tab2, proportion=0, flag=wx.EXPAND | wx.LEFT | wx.BOTTOM, border=2)

        # File list
        self.file_list_tab2 = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.file_list_tab2.InsertColumn(0, "Filename", width=200)
        self.file_list_tab2.InsertColumn(1, "File Size (KB)", width=50)
        self.file_list_tab2.InsertColumn(2, "Date Modified", width=150)
        self.file_list_tab2.Bind(wx.EVT_LIST_COL_CLICK, self.on_column_click_tab2)
        self.file_list_tab2.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_file_selected_tab2)
        self.file_list_tab2.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_file_deselected_tab2)
        left_vbox.Add(self.file_list_tab2, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.TOP | wx.BOTTOM, border=2)

        # Download buttons
        download_buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.download_file_btn = wx.Button(left_panel, label="Download File")
        self.download_file_btn.Bind(wx.EVT_BUTTON, self.on_download_file)
        self.download_file_btn.Disable()  # Disable by default
        download_buttons_hbox.Add(self.download_file_btn, proportion=0, flag=wx.ALL, border=2)

        self.download_all_files_btn = wx.Button(left_panel, label="Download All Files")
        self.download_all_files_btn.Bind(wx.EVT_BUTTON, self.on_download_all_files)
        self.download_all_files_btn.Disable()  # Disable by default
        download_buttons_hbox.Add(self.download_all_files_btn, proportion=0, flag=wx.ALL, border=2)

        left_vbox.Add(download_buttons_hbox, proportion=0, flag=wx.EXPAND | wx.ALL, border=2)

        # Set the sizer for the left panel
        left_panel.SetSizer(left_vbox)

        # Right side: File properties and Player info
        right_panel = wx.Panel(self.splitter_tab2)
        right_vbox = wx.BoxSizer(wx.VERTICAL)

        # Address bar for the right side (if needed, otherwise remove this)
        right_address_hbox = wx.BoxSizer(wx.HORIZONTAL)
        right_address_label = wx.StaticText(right_panel, label="Selected File:")
        right_address_hbox.Add(right_address_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.ALL, border=2)
        self.selected_file_path_tab2 = wx.TextCtrl(right_panel, style=wx.TE_READONLY)
        right_address_hbox.Add(self.selected_file_path_tab2, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        right_vbox.Add(right_address_hbox, proportion=0, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)

        # Create a splitter for the File Properties and Player info sections
        self.right_splitter_tab2 = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        self.right_splitter_tab2.SetMinimumPaneSize(50)  # Set a minimum size for each pane

        # File properties section (top pane)
        properties_panel = wx.Panel(self.right_splitter_tab2)
        # properties_box = wx.StaticBox(properties_panel, label="File Properties")
        # properties_sizer = wx.StaticBoxSizer(properties_box, wx.VERTICAL)
        properties_sizer = wx.BoxSizer(wx.VERTICAL)
        self.properties_list_tab2 = wx.ListCtrl(properties_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.properties_list_tab2.InsertColumn(0, "Property", width=150)
        self.properties_list_tab2.InsertColumn(1, "Value", width=400)
        properties_sizer.Add(self.properties_list_tab2, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        properties_panel.SetSizer(properties_sizer)

        # Player info section (bottom pane)
        player_info_panel = wx.Panel(self.right_splitter_tab2)
        # dummy_box = wx.StaticBox(player_info_panel, label="Player info")
        # player_info_sizer = wx.StaticBoxSizer(dummy_box, wx.VERTICAL)
        player_info_sizer = wx.BoxSizer(wx.VERTICAL)
        self.details_list_tab2 = wx.ListCtrl(player_info_panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.details_list_tab2.InsertColumn(0, 'Team', width=50)
        self.details_list_tab2.InsertColumn(1, 'Hex IP', width=80)
        self.details_list_tab2.InsertColumn(2, 'Player Names', width=100)
        self.details_list_tab2.InsertColumn(3, 'Faction', width=200)
        self.details_list_tab2.InsertColumn(4, 'Surrender/Exit?', width=80)
        self.details_list_tab2.InsertColumn(5, 'Surrender', width=80)
        self.details_list_tab2.InsertColumn(6, 'Exit', width=80)
        self.details_list_tab2.InsertColumn(7, 'Idle/Kicked?', width=80)
        self.details_list_tab2.InsertColumn(8, 'Last CRC', width=80)
        self.details_list_tab2.InsertColumn(9, 'Placement', width=50)
        player_info_sizer.Add(self.details_list_tab2, proportion=1, flag=wx.EXPAND | wx.RIGHT | wx.BOTTOM, border=2)
        player_info_panel.SetSizer(player_info_sizer)

        # Split the right section vertically
        self.right_splitter_tab2.SplitHorizontally(properties_panel, player_info_panel, sashPosition=350)  # Initial sash position

        # Add the right splitter to the right panel's sizer
        right_vbox.Add(self.right_splitter_tab2, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)

        # Set the sizer for the right panel
        right_panel.SetSizer(right_vbox)

        # Split the main window vertically
        self.splitter_tab2.SplitVertically(left_panel, right_panel, sashPosition=350)  # Initial sash position

        # Add the splitter to the vertical sizer
        vbox.Add(self.splitter_tab2, proportion=1, flag=wx.EXPAND | wx.ALL, border=2)

        # Set the sizer for the second tab
        self.tab2.SetSizer(vbox)

        # Store the full list of online files for filtering
        self.full_online_file_list = []

    
    def on_select_directory(self, event):
        # Open a directory dialog
        dialog = wx.DirDialog(self, "Choose a directory containing .rep files", style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() == wx.ID_OK:
            selected_dir = dialog.GetPath()
            self.dir_path.SetValue(selected_dir)
            self.update_file_list(selected_dir)
            self.rename_all_files_btn.Enable()  # Enable "Rename All Files" button
        dialog.Destroy()

    
    def update_file_list(self, directory):
        """Update the list of .rep files in the directory."""
        self.file_list.DeleteAllItems()  # Clear the list
        self.full_file_list = []  # Reset the full file list
        for filename in os.listdir(directory):
            if filename.endswith(".rep"):
                filepath = os.path.join(directory, filename)
                filesize = os.path.getsize(filepath) / 1024  # Convert to KB
                modified_time = os.path.getmtime(filepath)
                modified_date = datetime.datetime.fromtimestamp(modified_time).strftime("%Y-%m-%d %H:%M:%S")

                # Add the file details to the full list
                self.full_file_list.append((filename, filesize, modified_date))

        # Display all files initially
        self.filter_file_list("")

    
    def filter_file_list(self, search_text):
        """Filter the file list based on the search text."""
        self.file_list.DeleteAllItems()  # Clear the list
        search_text = search_text.lower()  # Case-insensitive search
        for filename, filesize, modified_date in self.full_file_list:
            if search_text in filename.lower():
                index = self.file_list.InsertItem(self.file_list.GetItemCount(), filename)
                self.file_list.SetItem(index, 1, f"{filesize:.2f}")
                self.file_list.SetItem(index, 2, modified_date)

    
    def on_search(self, event):
        """Handle search events (real-time filtering)."""
        search_text = self.search_ctrl.GetValue()
        self.filter_file_list(search_text)

    
    def on_search_cancel(self, event):
        """Handle search cancel events."""
        self.search_ctrl.Clear()
        self.filter_file_list("")

    
    def on_column_click(self, event):
        """Sort the list based on the clicked column and toggle the sort order."""
        col = event.GetColumn()

        # If the same column is clicked again, toggle the sort order
        if col == self.sort_column:
            self.sort_ascending = not self.sort_ascending
        else:
            # If a different column is clicked, sort in ascending order by default
            self.sort_column = col
            self.sort_ascending = True

        # Sort the file list
        self.sort_file_list(col, self.sort_ascending)

    
    def sort_file_list(self, col, ascending):
        """Sort the file list based on the specified column and order."""
        items = []
        for i in range(self.file_list.GetItemCount()):
            filename = self.file_list.GetItemText(i)
            filesize = float(self.file_list.GetItem(i, 1).GetText())
            modified_date = self.file_list.GetItem(i, 2).GetText()
            items.append((filename, filesize, modified_date))

        # Define sorting logic for each column
        if col == 0:  # Sort by filename
            items.sort(key=lambda x: x[0].lower(), reverse=not ascending)
        elif col == 1:  # Sort by file size
            items.sort(key=lambda x: x[1], reverse=not ascending)
        elif col == 2:  # Sort by date modified
            items.sort(key=lambda x: datetime.datetime.strptime(x[2], "%Y-%m-%d %H:%M:%S"), reverse=not ascending)

        # Update the list control with sorted items
        self.file_list.DeleteAllItems()
        for item in items:
            index = self.file_list.InsertItem(self.file_list.GetItemCount(), item[0])
            self.file_list.SetItem(index, 1, f"{item[1]:.2f}")
            self.file_list.SetItem(index, 2, item[2])

    
    def on_file_selected(self, event):
        """Handle file selection events."""
        self.rename_file_btn.Enable()  # Enable "Rename File" button
        self.update_file_properties(event.GetIndex())

    
    def on_file_deselected(self, event):
        """Handle file deselection events."""
        self.rename_file_btn.Disable()  # Disable "Rename File" button
        self.clear_file_properties()

    
    def update_file_properties(self, index):
        """Update file properties when a file is selected."""
        selected_file = self.file_list.GetItemText(index)
        filepath = os.path.join(self.dir_path.GetValue(), selected_file)

        # Update the selected file path in the address bar
        # self.selected_file_path.SetValue(filepath)
        self.selected_file_path = filepath

        # Clear previous properties
        self.properties_list.DeleteAllItems()

        file_info_prop, file_info_2 = replay_result.get_replay_info(filepath, 1)

        rgb_values = {
            "Gold": (204, 153, 0),
            "Red": (200, 0, 0),
            "Blue": (0, 102, 204),
            "Green": (0, 128, 0),
            "Orange": (225, 100, 0),
            "Cyan": (0, 150, 180),
            "Purple": (128, 0, 128),
            "Pink": (200, 50, 150),
        }
        for prop, value in file_info_prop[:-1]:
            if (prop == "SW Restriction") and (value == "Unknown"):
                continue
            idx = self.properties_list.InsertItem(self.properties_list.GetItemCount(), prop)
            self.properties_list.SetItem(idx, 1, str(value))

            # Set the color based on 
            if prop == "Match Result":
                if 'Win' in value:  # example threshold in bytes
                    self.properties_list.SetItemTextColour(idx, wx.Colour(0, 128, 0))  # green
                else:
                    self.properties_list.SetItemTextColour(idx, wx.Colour(200, 0, 0))  # red

            if prop == "EXE check (1.04)":
                if value == 'Failed':  # example threshold in bytes
                    self.properties_list.SetItemTextColour(idx, wx.Colour(200, 0, 0))  # red
            if prop == "INI check (1.04)":
                if value == 'Failed':  # example threshold in bytes
                    self.properties_list.SetItemTextColour(idx, wx.Colour(200, 0, 0))  # red
            if prop == "Player Name":
                self.properties_list.SetItemTextColour(idx, wx.Colour(rgb_values.get(file_info_prop[-1][1], (0, 0, 0))))  # red

        self.details_list.DeleteAllItems()
        details = file_info_2
        # Define a bold font
        # bold_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        for detail in details:
            text_values = detail[:-1]
            color_name = detail[-1]  # Last value is the color name
            
            idx = self.details_list.InsertItem(self.details_list.GetItemCount(), text_values[0])
            for col, value in enumerate(text_values[0:], start=0):
                self.details_list.SetItem(idx, col, str(value))
            self.details_list.SetItemTextColour(idx, rgb_values.get(color_name, (0, 0, 0)))  # Apply text color
            # self.details_list.SetItemFont(idx, bold_font)


    def clear_file_properties(self):
        """Clear file properties when no file is selected."""
        # self.selected_file_path.SetValue("")
        self.properties_list.DeleteAllItems()
        self.details_list.DeleteAllItems()

    
    def add_property(self, label, value):
        """Add a property to the properties list."""
        index = self.properties_list.InsertItem(self.properties_list.GetItemCount(), label)
        self.properties_list.SetItem(index, 1, value)

    
    def on_rename_file(self, event):
        """Rename the selected files and keep them selected."""
        selected_indices = []
        
        # Get all selected indices using GetFirstSelected() and GetNextSelected()
        index = self.file_list.GetFirstSelected()
        while index != -1:
            selected_indices.append(index)
            index = self.file_list.GetNextSelected(index)

        if not selected_indices:
            return  # No files selected

        renamed_files = []

        try:
            for index in selected_indices:
                selected_file = self.file_list.GetItemText(index)
                filepath = os.path.join(self.dir_path.GetValue(), selected_file)
                new_filename = self.rename_file(filepath, selected_file)  # Rename and get new filename
                renamed_files.append(new_filename)

            # Refresh the file list after renaming
            self.update_file_list(self.dir_path.GetValue())

            # Re-select the renamed files
            for index in range(self.file_list.GetItemCount()):
                new_filename = self.file_list.GetItemText(index)
                if new_filename in renamed_files:
                    self.file_list.Select(index)
                    self.file_list.Focus(index)

            wx.MessageBox(f"{len(renamed_files)} file(s) renamed successfully!", "Success", wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(f"Error renaming files: {e}", "Error", wx.OK | wx.ICON_ERROR)

    
    def on_rename_all_files(self, event):
        """Rename all files in the directory."""
        directory = self.dir_path.GetValue()
        try:
            for filename in os.listdir(directory):
                if filename.endswith(".rep"):
                    filepath = os.path.join(directory, filename)
                    self.rename_file(filepath, filename)
            wx.MessageBox("All files renamed successfully!", "Success", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Error renaming files: {e}", "Error", wx.OK | wx.ICON_ERROR)
        self.update_file_list(self.dir_path.GetValue())

    
    def rename_file(self, filepath, current_filename):
        """Rename a file and return the new filename."""
        
        base_name = replay_result.get_replay_info(filepath, 1, True)
        new_filename = f"{base_name}.rep"
        new_filepath = os.path.join(os.path.dirname(filepath), new_filename)

        # Handle duplicate filenames
        counter = 1
        while os.path.exists(new_filepath):
            if new_filename == current_filename:
                return new_filename  # No change, return early
            else:
                new_filename = f"{base_name}_{counter}.rep"
                new_filepath = os.path.join(os.path.dirname(filepath), new_filename)
                counter += 1

        # Rename the file
        os.rename(filepath, new_filepath)

        return new_filename  # Return new name

    
    def on_fetch_files(self, event):
        """Fetch files from the online address."""
        online_address = self.online_address.GetValue()
        if not online_address:
            wx.MessageBox("Please enter a valid gentool address.", "Error", wx.OK | wx.ICON_ERROR)
            return

        if 'gentool.net/data' in online_address:
            try:
                # Fetch the list of files from the online address
                response = requests.get(online_address)
                if response.status_code != 200:
                    wx.MessageBox(f"Failed to fetch files: {response.status_code}", "Error", wx.OK | wx.ICON_ERROR)
                    return
                
                if online_address[-1] != '/':
                    online_address += '/'
                
                doc = BeautifulSoup(response.content, "lxml")
                rows = doc.find_all('tr')
                gt_files = []

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
                        divisor = 1
                        if 'K' not in file_size:
                            divisor = 1024
                        file_size_numeric = int(re.sub(r'\D', '', file_size))/divisor
                        gt_files.append([file_name, file_size_numeric, date_time])

                # Update the file list
                self.file_list_tab2.DeleteAllItems()
                self.full_online_file_list = []
                for filename in gt_files:
                    # index = self.file_list_tab2.InsertItem(self.file_list_tab2.GetItemCount(), filename)
                    index = self.file_list_tab2.InsertItem(self.file_list.GetItemCount(), filename[0])
                    self.file_list_tab2.SetItem(index, 1, f"{filename[1]:.2f}")
                    self.file_list_tab2.SetItem(index, 2, filename[2])
                    self.full_online_file_list.append(filename)


                # Enable download buttons
                self.download_all_files_btn.Enable()

            except Exception as e:
                wx.MessageBox(f"Error fetching files: {e}", "Error", wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox("Please enter link from gentool.net/data", "Error")

        
    def on_search_tab2(self, event):
        """Handle search events (real-time filtering) for Tab 2."""
        search_text = self.search_ctrl_tab2.GetValue()
        self.filter_file_list_tab2(search_text)

    
    def on_search_cancel_tab2(self, event):
        """Handle search cancel events for Tab 2."""
        self.search_ctrl_tab2.Clear()
        self.filter_file_list_tab2("")

    
    def filter_file_list_tab2(self, search_text):
        """Filter the file list based on the search text for Tab 2."""
        self.file_list_tab2.DeleteAllItems()  # Clear the list
        search_text = search_text.lower()  # Case-insensitive search
        for filename, filesize, modified_date in self.full_online_file_list:
            if search_text in filename.lower():
                index = self.file_list_tab2.InsertItem(self.file_list_tab2.GetItemCount(), filename)
                self.file_list_tab2.SetItem(index, 1, f"{filesize:.2f}")
                self.file_list_tab2.SetItem(index, 2, modified_date)


    def on_column_click_tab2(self, event):
        """Sort the list based on the clicked column and toggle the sort order for Tab 2."""
        col = event.GetColumn()

        # If the same column is clicked again, toggle the sort order
        if col == self.sort_column:
            self.sort_ascending = not self.sort_ascending
        else:
            # If a different column is clicked, sort in ascending order by default
            self.sort_column = col
            self.sort_ascending = True

        # Sort the file list
        self.sort_file_list_tab2(col, self.sort_ascending)

    
    def sort_file_list_tab2(self, col, ascending):
        """Sort the file list based on the specified column and order for Tab 2."""
        items = []
        for i in range(self.file_list_tab2.GetItemCount()):
            filename = self.file_list_tab2.GetItemText(i)
            filesize = float(self.file_list_tab2.GetItem(i, 1).GetText())
            modified_date = self.file_list_tab2.GetItem(i, 2).GetText()
            items.append((filename, filesize, modified_date))

        # Define sorting logic for each column
        if col == 0:  # Sort by filename
            items.sort(key=lambda x: x[0].lower(), reverse=not ascending)
        elif col == 1:  # Sort by file size
            items.sort(key=lambda x: x[1], reverse=not ascending)
        elif col == 2:  # Sort by date modified
            items.sort(key=lambda x: datetime.datetime.strptime(x[2], "%Y-%m-%d %H:%M"), reverse=not ascending)

        # Update the list control with sorted items
        self.file_list_tab2.DeleteAllItems()
        for item in items:
            index = self.file_list_tab2.InsertItem(self.file_list_tab2.GetItemCount(), item[0])
            self.file_list_tab2.SetItem(index, 1, f"{item[1]:.2f}")
            self.file_list_tab2.SetItem(index, 2, item[2])


    def on_file_selected_tab2(self, event):
        """Handle file selection events for Tab 2."""
        self.download_file_btn.Enable()  # Enable "Download File" button
        self.update_file_properties_tab2(event.GetIndex())

    
    def on_file_deselected_tab2(self, event):
        """Handle file deselection events for Tab 2."""
        self.download_file_btn.Disable()  # Disable "Download File" button
        self.clear_file_properties_tab2()


    def update_file_properties_tab2(self, index):
        """Update file properties when a file is selected for Tab 2."""

        selected_file = self.file_list_tab2.GetItemText(index)
        online_address = self.online_address.GetValue()
        file_url = urljoin(online_address, selected_file)

        # Update the selected file path in the address bar
        self.selected_file_path_tab2.SetValue(file_url)

        # Clear previous properties
        self.properties_list_tab2.DeleteAllItems()
        file_info_prop_tab2, file_info_2_tab2 = replay_result.get_replay_info(file_url, 2)
        
        # Add file properties to the list
        rgb_values = {
            "Gold": (204, 153, 0),
            "Red": (200, 0, 0),
            "Blue": (0, 102, 204),
            "Green": (0, 128, 0),
            "Orange": (225, 100, 0),
            "Cyan": (0, 150, 180),
            "Purple": (128, 0, 128),
            "Pink": (200, 50, 150),
        }


        for prop, value in file_info_prop_tab2[:-1]:
            if (prop == "SW Restriction") and (value == "Unknown"):
                continue
            idx = self.properties_list_tab2.InsertItem(self.properties_list_tab2.GetItemCount(), prop)
            self.properties_list_tab2.SetItem(idx, 1, str(value))

            # Set the color based on 
            if prop == "Match Result":
                if 'Win' in value:  # example threshold in bytes
                    self.properties_list_tab2.SetItemTextColour(idx, wx.Colour(34, 139, 34))  # green
                else:
                    self.properties_list_tab2.SetItemTextColour(idx, wx.Colour(255, 0, 0))  # red

            if prop == "EXE check (1.04)":
                if value == 'Failed':  # example threshold in bytes
                    self.properties_list_tab2.SetItemTextColour(idx, wx.Colour(255, 0, 0))  # red
            if prop == "INI check (1.04)":
                if value == 'Failed':  # example threshold in bytes
                    self.properties_list_tab2.SetItemTextColour(idx, wx.Colour(255, 0, 0))  # red
            if prop == "Player Name":
                self.properties_list_tab2.SetItemTextColour(idx, wx.Colour(rgb_values.get(file_info_prop_tab2[-1][1], (0, 0, 0))))  # red

        self.details_list_tab2.DeleteAllItems()
        details = file_info_2_tab2
        # Define a bold font
        # bold_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        for detail in details:
            text_values = detail[:-1]
            color_name = detail[-1]  # Last value is the color name
            idx = self.details_list_tab2.InsertItem(self.details_list_tab2.GetItemCount(), text_values[0])
            for col, value in enumerate(text_values[0:], start=0):
                self.details_list_tab2.SetItem(idx, col, str(value))
            self.details_list_tab2.SetItemTextColour(idx, rgb_values[color_name])  # Apply text color
            # self.details_list.SetItemFont(idx, bold_font)
            
    
    def clear_file_properties_tab2(self):
        """Clear file properties when no file is selected for Tab 2."""
        self.selected_file_path_tab2.SetValue("")
        self.properties_list_tab2.DeleteAllItems()
        self.details_list_tab2.DeleteAllItems()

    
    def add_property_tab2(self, label, value):
        """Add a property to the properties list for Tab 2."""
        index = self.properties_list_tab2.InsertItem(self.properties_list_tab2.GetItemCount(), label)
        self.properties_list_tab2.SetItem(index, 1, value)

    
    def on_download_file(self, event):
        """Download the selected files with a progress bar and keep them selected."""
        selected_indices = []

        # Get all selected indices
        index = self.file_list_tab2.GetFirstSelected()
        while index != -1:
            selected_indices.append(index)
            index = self.file_list_tab2.GetNextSelected(index)

        if not selected_indices:
            return  # No files selected

        online_address = self.online_address.GetValue()
        
        # Open a directory dialog to select the download location
        dialog = wx.DirDialog(self, "Choose a directory to save the files", style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() == wx.ID_OK:
            save_dir = dialog.GetPath()
            downloaded_files = []
            
            # Create a progress dialog
            progress_dialog = wx.ProgressDialog(
                "Downloading Files",
                "Downloading...",
                maximum=len(selected_indices),
                parent=self,
                style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL
            )

            try:
                for i, index in enumerate(selected_indices):
                    selected_file = self.file_list_tab2.GetItemText(index)
                    file_url = urljoin(online_address, selected_file)

                    self.download_file(file_url, save_dir, selected_file, progress_dialog)  # Pass progress dialog
                    downloaded_files.append(selected_file)

                    # Update progress
                    progress_dialog.Update(i + 1, f"Downloading {selected_file}...")

                progress_dialog.Destroy()
                wx.MessageBox(f"{len(downloaded_files)} file(s) downloaded successfully!", "Success", wx.OK | wx.ICON_INFORMATION)

                # Re-select the downloaded files
                for index in range(self.file_list_tab2.GetItemCount()):
                    if self.file_list_tab2.GetItemText(index) in downloaded_files:
                        self.file_list_tab2.Select(index)
                        self.file_list_tab2.Focus(index)

            except Exception as e:
                progress_dialog.Destroy()
                wx.MessageBox(f"Error downloading files: {e}", "Error", wx.OK | wx.ICON_ERROR)

        dialog.Destroy()

    
    def on_download_all_files(self, event):
        """Download all files from the online address with a detailed progress bar."""
        online_address = self.online_address.GetValue()
        
        # Open a directory dialog to select the download location
        dialog = wx.DirDialog(self, "Choose a directory to save the files", style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() == wx.ID_OK:
            save_dir = dialog.GetPath()
            downloaded_files = []
            total_files = len(self.full_online_file_list)

            # Create a progress dialog for tracking overall progress
            progress_dialog = wx.ProgressDialog(
                "Downloading Files",
                "Preparing download...",
                maximum=total_files,
                parent=self,
                style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL
            )
            progress_dialog.SetSize((500, 150))  # Set width to 500px
            progress_dialog.Fit()

            try:
                for i, filename in enumerate(self.full_online_file_list):
                    file_url = urljoin(online_address, filename[0])  # Construct file URL
                    
                    # Download file with per-file progress tracking
                    self.download_file(file_url, save_dir, filename[0], progress_dialog, i + 1, total_files)
                    
                    downloaded_files.append(filename[0])

                    # Update the overall progress bar
                    progress_dialog.Update(i + 1, f"Downloaded {filename[0]} ({i+1}/{total_files})")

                progress_dialog.Destroy()
                wx.MessageBox(f"All {total_files} file(s) downloaded successfully!", "Success", wx.OK | wx.ICON_INFORMATION)

            except Exception as e:
                progress_dialog.Destroy()
                wx.MessageBox(f"Error downloading files: {e}", "Error", wx.OK | wx.ICON_ERROR)

        dialog.Destroy()


    def download_file(self, file_url, save_dir, filename, progress_dialog=None, file_index=1, total_files=1):
        """Download a file with detailed progress updates."""
        response = requests.get(file_url, stream=True)
        if response.status_code != 200:
            raise Exception(f"Failed to download file: {response.status_code}")

        save_path = os.path.join(save_dir, filename)
        total_size = int(response.headers.get("content-length", 0))  # Get total file size
        chunk_size = 8192
        downloaded_size = 0

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)

                    # Update progress bar with actual file percentage
                    if progress_dialog and total_size:
                        percent = int((downloaded_size / total_size) * 100)
                        progress_dialog.Update(file_index, f"Downloading {filename} ({percent}% complete)")

                    wx.Yield()  # Keep the UI responsive


class ReplayViewer(wx.App):
    def OnInit(self):
        self.frame = MyFrame(None)
        return True
