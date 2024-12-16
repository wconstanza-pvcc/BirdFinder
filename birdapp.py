import customtkinter as ctk
import tkinter as tk
import tkintermapview as tkmap
import ebird.api as ebird
import webbrowser
import birdtool
import copy
from dotenv import load_dotenv, dotenv_values
import datetime
import time
import threading
import json
import os

load_dotenv('ebird_key.env')
api_key = os.getenv('EBIRD_ACCESS')

ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('dark-blue')

# Frame template for displaying observation data 
class birdFrame(ctk.CTkFrame):
    def __init__(self, parent, data):
        super().__init__(parent)

        self.observation_data = data
        # Creating a link to the eBird page for the current species
        self.bird_link = f"https://ebird.org/species/{self.observation_data['species_code']}/"

        self.grid_rowconfigure((0,3), weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.name = self.observation_data['common_name']
        self.time_since = self.observation_data['time_since']
        self.num = self.observation_data['num_obs']
        self.count = self.observation_data['checklist_count']

        # Setting display text based on observation data values
        self.last_seen = None

        if self.time_since > 1:
            self.last_seen = f"Last seen {self.time_since} days ago"
        elif self.time_since == 1:
            self.last_seen = f"Last seen 1 day ago"
        else:
            self.last_seen = f"Last seen today"

        self.num_seen = f"Latest observation count: {self.num}"

        self.countstr = None

        if self.count > 1:
            self.countstr = f"Counted in {self.count} unique checklists"
        else:
            self.countstr = f"Counted in 1 unique checklist"
        
        self._border_width = 2

        self.nameLabel = ctk.CTkLabel(self, text=self.name, text_color='White', font=('Arial', 18, 'bold'), anchor='center')
        self.nameLabel.grid(row=0, column=0, padx=5, pady=10, sticky='nsew')

        # Bind events to the nameLabel widget; allows user to access eBird species page on click
        self.nameLabel.bind('<Button-1>', self.open_bird_page)
        self.nameLabel.bind('<Enter>', self.hover_enter)
        self.nameLabel.bind('<Leave>', self.hover_leave)

        self.dateLabel = ctk.CTkLabel(self, text=self.last_seen, font=('Arial', 16), anchor='center')
        self.dateLabel.grid(row=1, column=0, padx=5, pady=(0,5), sticky='nsew')

        self.numLabel = ctk.CTkLabel(self, text=self.num_seen, font=('Arial', 16), anchor='center')
        self.numLabel.grid(row=2, column=0, padx=5, pady=5, sticky='nsew')

        self.countLabel = ctk.CTkLabel(self, text=self.countstr, font=('Arial', 16), anchor='center')
        self.countLabel.grid(row=3, column=0, padx=5, pady=(5,10), sticky='nsew')
    
    # Opens a page in the default browser
    def open_bird_page(self, event):
        webbrowser.open(self.bird_link)

    def hover_enter(self, event):
        self.nameLabel.configure(text='Click for more info', text_color = '#808080', font=('Arial', 18, 'bold', 'underline'))
    
    def hover_leave(self, event):
        self.nameLabel.configure(text=self.name, text_color = 'White', font=('Arial', 18, 'bold'))

# Frame for storing the map widget and related widgets
class mapFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)

        # Control values for handling functions
        self.thread_lock = threading.Lock()
        self.command_lock = False
        self.last_zoom = None
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=10)

        # Initializing the map
        self.base_map()
        self.marker_attributes = self.create_markers(parent)
        self.zoom_polling()

        # Lets the user change map location by typing an address
        self.address = ctk.CTkEntry(self, placeholder_text='Enter an address', )
        self.address.grid(row=0, column=0, padx=10, pady=10, sticky='ew')
        self.address.bind('<Return>', self.change_address)

    def base_map(self):

        '''Creates a map instance and sets default values'''

        self.map = tkmap.TkinterMapView(self)
        self.map.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.map.set_address('Charlottesville, Virginia, USA')
        self.map.set_zoom(15)
        self.map.grid(row=1, column=0, columnspan=5, padx=0, pady=0, sticky='nsew')
        return(self.map)

    def change_address(self, event):
        '''Changes the currently displayed map address'''
        new_address = self.address.get()
        self.map.set_address(new_address)

    def create_markers(self, parent):

        '''Initializes marker objects for all cached hotspots and draws them onto the map widget'''

        marker_attrlist = []
        for spot in parent.hotspots:
            pos = (spot.get('lat'), spot.get('lng'))
            name = spot.get('locName')
            id = spot.get('locId')
            days_back = 14
            locMarker = self.map.set_marker(pos[0], pos[1], text=name)
            locMarker.data = birdtool.BirdDataHandler(api_key, id, days_back)
            locMarker.command = lambda m=locMarker: threading.Thread(target=self.observation_unpacker, args=(m,)).start()

            # Store marker attributes to reinitialize later
            marker_attrlist.append({
                'pos': (pos),
                'name': name,
                'data': copy.copy(locMarker.data),
                'command': locMarker.command
                })
            
        return(marker_attrlist)

    # Updates marker visibility based on map zoom to avoid clutter
    def update_markers(self, zoom):

        '''Controls marker visibility on the map based on map zoom'''

        if zoom <= 11.5 and self.map.canvas_marker_list:
            self.map.delete_all_marker()
            # Reconfigure cursor on map canvas widget to avoid 'frozen' cursor
            self.map.canvas.configure(cursor='')
        elif zoom >= 11.5 and not self.map.canvas_marker_list:
            # Utilizes stored marker attributes to redraw markers
            for marker in self.marker_attributes:
                pos = marker['pos']
                locMarker = tkmap.map_widget.CanvasPositionMarker(self.map, (pos[0], pos[1]), text=marker['name'])
                locMarker.data = marker['data']
                locMarker.command = marker['command']
                locMarker.draw()
                self.map.canvas_marker_list.append(locMarker)

    def zoom_polling(self):

        '''Polls the map in 100ms intervals to check map zoom conditions \n
        Controls minimum zoom and prompts marker updates'''

        current_zoom = self.map.zoom

        # Zoom limits based on markers existing, avoids heavy lag
        if self.map.canvas_marker_list:
            self.map.min_zoom = 10
        else:
            self.map.min_zoom = 0
        # Prompts a marker update check
        if current_zoom != self.last_zoom:
            self.last_zoom = current_zoom
            self.update_markers(current_zoom)
        self.after(100, self.zoom_polling)
    
    def observation_unpacker(self, marker):

        '''Unpacks observation data values from a hotspot into a dictionary and passes it to be displayed on the GUI'''

        # Terminates function if data is already loading or location is already displayed
        if self.command_lock == True or marker.text == self.master.current_location:
            return
        
        # Locks further functions from being executed to avoid deletion of objects being drawn
        self.command_lock = True
        # Possibly redundant with the command lock
        with self.thread_lock:
            self.observations = marker.data.sort_observations()
            self.obs_json = [bird.__dict__ for bird in self.observations.values()]
        self.master.after(0, self.master.display_data, self.obs_json, marker.text)

# Main GUI window
class birdApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.current_location = ''

        # Window and file initialization
        self.title('Bird Tracker')
        self.set_window()
        self.taxonomy = birdtool.load_taxonomy()
        self.hotspots = birdtool.load_hotspots()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(0, weight=1)

        # Holds widgets related to the display of bird data
        self.display_frame = ctk.CTkFrame(self)
        self.display_frame.grid(row=0, column=0, padx=5, pady=5, sticky='nsew')
        self.display_frame.grid_columnconfigure(0, weight=1)
        self.display_frame.grid_rowconfigure(0, weight=1)
        self.display_frame.grid_rowconfigure(2, weight=10)

        self.bird_search = ctk.CTkEntry(self.display_frame, 
                                        placeholder_text='Enter species name')
        
        self.bird_search.grid(row=0, column=0, padx=10, pady=10, sticky='ew')
        self.bird_search.bind('<Return>', self.search_bird)

        # Makes a label to help the user remember where the data comes from
        self.location_label = ctk.CTkLabel(self.display_frame, 
                                           text=f"Current hotspot: {self.current_location}", 
                                           font=('arial', 14, 'bold'),
                                           wraplength=225,
                                           anchor='center')
        
        self.location_label.grid(row=1, column=0, padx=10, pady=(0,15))

        self.data_frame = ctk.CTkScrollableFrame(self.display_frame)
        self.data_frame.grid(row=2, column=0, padx=0, pady=0, sticky='nsew')
        self.data_frame.grid_rowconfigure(0, weight=1)
        self.data_frame.grid_columnconfigure(0, weight=1)

        # Create an instance of the mapFrame class and assign it to the grid
        self.mapframe = mapFrame(self)
        self.mapframe.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')

    def set_window(self, width_ratio: float=0.75, height_ratio: float=0.75):
        
        '''Sets the window size relative to the screen and centers it'''

        # Gathers the screen's width and height in pixels
        s_width = self.winfo_screenwidth()
        s_height = self.winfo_screenheight()

        # Generates the width and height of the window relative to the screen
        w_width = int(s_width * width_ratio)
        w_height = int(s_height * height_ratio)

        # Coordinates for centering the window
        x = int(s_width / 2) - int(w_width / 2) 
        y = int(s_height / 2) - int(w_height / 2)

        # Creates the window geometry and sets a minimum size
        self.geometry(f'{w_width}x{w_height}+{x}+{y}')
        self.minsize(w_width, w_height)

    def display_data(self, data, name):

        '''Displays passed observation data within birdFrame objects'''
        
        # Clears any existing frame objects
        for frame in self.data_frame.winfo_children():
            if isinstance(frame, birdFrame) and frame.winfo_exists():
                frame.destroy()
        
        # Set current location and update the label
        self.current_location = name
        self.location_label.configure(text=f"Current hotspot: {self.current_location}")

        # Placeholder text must be configured separately to actually update the widget.
        self.bird_search.configure(placeholder_text='Loading...')
        self.bird_search.configure(state='disabled')

        def create_frames():

            '''Creates a list of birdFrame instances mapping to hotspot observation data'''

            frames = [birdFrame(self.data_frame, bird) for bird in data]
            self.data_frame.after(0, lambda: grid_loader(frames, delay=100))

        def grid_loader(frames, delay, i=0):

            '''Loads a list of frames individually \n
            Done to avoid lag associated with bulk loading'''

            if i < len(frames):
                frames[i].grid(row=i, column=0, padx=5, pady=5, sticky='nsew')
                self.data_frame.after(delay, lambda: grid_loader(frames, delay, i + 1))
            else:
                # Allows marker commands to be run again after bird frames finish loading
                self.mapframe.command_lock = False
                # Configure in opposite order to update placeholder text when state is normal
                self.bird_search.configure(state='normal')
                self.bird_search.configure(placeholder_text='Enter species name')
                self.data_frame._parent_canvas.yview_moveto(0)

        threading.Thread(target=create_frames).start()

    def search_bird(self, event):

        '''Modifies the currently displayed frames to show birds matching a search entry'''

        # Normalizing the user's entry for matching
        entry_string = self.bird_search.get().strip().lower()
        # Grabs all children of the data frame widget
        current_frames = self.data_frame.winfo_children()
        
        # Matches search bar entry with bird commons names and displays matching frames
        for frame in current_frames:
            if not entry_string or entry_string in frame.name.lower():
                frame.grid()
            else:
                frame.grid_remove()
        
        # Resets to the top of the scrollbar
        # Avoids the user being outside of the currently displayed frames
        self.data_frame._parent_canvas.yview_moveto(0)

if __name__ == '__main__':
    app = birdApp()
    app.mainloop()