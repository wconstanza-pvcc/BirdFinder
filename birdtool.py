import ebird.api as ebird
import datetime
from dataclasses import dataclass
from dotenv import load_dotenv, dotenv_values
import json
import os

load_dotenv('ebird_key.env')
api_key = os.getenv('EBIRD_ACCESS')

def create_taxonomy_cache():

    '''Creates a taxonomy cache file for all bird species supported by eBird'''

    taxonomy_cache = {}
    taxonomy = ebird.get_taxonomy(api_key)

    for taxa in taxonomy:
        common_name = taxa.get('comName')
        species_code = taxa.get('speciesCode')

        taxonomy_cache[species_code] = common_name
    
    return(taxonomy_cache)

def create_hotspot_cache(region='US-VA', days_back: int = 14):

    '''Creates a hotspot cache file for all active hotspots within a region for a certain day range'''

    current_time = datetime.datetime.now()
    cutoff = current_time - datetime.timedelta(days=days_back)
    hotspots = ebird.get_hotspots(api_key, region, days_back)

    # Returns the relevant keys from an iterated hotspot in dictionary form
    def format_hotspot(hotspot):
        return {'locName': hotspot.get('locName'),
                'locId': hotspot.get('locId'),
                'lat': hotspot.get('lat'),
                'lng': hotspot.get('lng'),
                'latestObsDt': hotspot.get('latestObsDt')
                }
    
    hotspot_cache = [
        format_hotspot(spot) for spot in hotspots
        if datetime.datetime.strptime(spot.get('latestObsDt', '1970-1-1 0:00'), '%Y-%m-%d %H:%M') >= cutoff 
        ]

    return(hotspot_cache)

def load_taxonomy():

    '''Loads or initializes the taxonomy cache'''

    taxonomy_path = 'taxonomy_cache.json'
    taxonomy_cache = []

    # If the cache file doesn't exist, creates a new one and returns the newly written file contents
    if not os.path.exists(taxonomy_path):
        taxonomy_cache = create_taxonomy_cache()
        with open(taxonomy_path, 'w') as f:
            f.write(json.dumps(taxonomy_cache, indent=4))
            return(taxonomy_cache)
    
    current_timestamp = datetime.datetime.now().timestamp()
    file_mod_time = os.path.getmtime(taxonomy_path)
    expiry_days = 180
    cache_expiry_date = current_timestamp - (expiry_days * 86400)

    # If the cache file exists, but is past 'expiry', regenerate it and return file contents
    if file_mod_time <= cache_expiry_date:
        taxonomy_cache = create_taxonomy_cache()
        with open(taxonomy_path, 'w') as f:
            f.write(json.dumps(taxonomy_cache, indent=4))
            return(taxonomy_cache)
    else:
        with open(taxonomy_path, 'r') as f:
            return(json.load(f))

# See comments on 'load_taxonomy' 
def load_hotspots():

    '''Loads or initializes the hotspot cache'''
    
    hotspot_path = 'hotspot_cache.json'
    hotspot_cache = []

    
    if not os.path.exists(hotspot_path):
        hotspot_cache = create_hotspot_cache()
        with open(hotspot_path, 'w') as f:
            f.write(json.dumps(hotspot_cache, indent=4))
            return(hotspot_cache)
        
    current_timestamp = datetime.datetime.now().timestamp()
    file_mod_time = os.path.getmtime(hotspot_path)
    expiry_days = 1
    cache_expiry_date = current_timestamp - (expiry_days * 86400)

    if file_mod_time <= cache_expiry_date:
        hotspot_cache = create_hotspot_cache()
        with open(hotspot_path, 'w') as f:
            f.write(json.dumps(hotspot_cache, indent=4))
            return(hotspot_cache)
    else:
        with open(hotspot_path, 'r') as f:
            return(json.load(f))

@dataclass
class ObservationData:
    species_code: str = ''
    common_name: str = ''
    num_obs: any = 0
    time_since: int = 0
    checklist_count: int = 0

    def update_observation(self, new_time, new_count):
        '''Updates an observation entry with the earliest data and keeps a record of individual sightings'''
        if new_time < self.time_since:
            self.time_since = new_time
            self.num_obs = new_count
        self.checklist_count += 1

class BirdDataHandler():

    def __init__(self, api_key, location, days_back: int = 14):

        self.api_key = api_key
        self.taxonomy = load_taxonomy()
        self.current_time = datetime.datetime.now()
        self.location = location
        self.days_back = days_back
        self.bird_dict = {}

    def gather_checklists(self):

        '''Gathers checklist codes from visits to a location within 14 days'''

        codes = []
        checklists = []

        if self.days_back > 14:
            return []
        
        for d in range(0, self.days_back):
            day_iter = self.current_time - datetime.timedelta(d)
            visits = ebird.get_visits(self.api_key, self.location, date=day_iter, max_results=100)

            for v in visits:
                visit_key = v.get('subId')
                codes.append(visit_key)
        
        for code in codes:
            checklist = ebird.get_checklist(self.api_key, code)
            checklists.append(checklist)

        return(checklists)
    
    def sort_observations(self):

        '''Gathers observation data from checklists and formats it into ObservationData objects \n
        Returns a dictionary of formatted observations sorted alphabetically by common name'''

        # Clear bird dict if the method has already been called in an instance
        if self.bird_dict:
            self.bird_dict = {}

        checklists = self.gather_checklists()

        for data in checklists:
            observations = data.get('obs')

            for obs in observations:
                obs_code = obs.get('speciesCode')
                # Get the time since as a number of seconds; enchances precision of observation updates
                obs_timesince = int((self.current_time - datetime.datetime.strptime(obs.get('obsDt'), '%Y-%m-%d %H:%M')).total_seconds())
                obs_count = int(obs.get('howManyStr')) if obs.get('howManyStr').isdigit() else str('X')

                if obs_code in self.bird_dict:
                    self.bird_dict.get(obs_code).update_observation(new_time=obs_timesince, new_count=obs_count)
                else:    
                    if obs_code in self.taxonomy:
                        common_name = self.taxonomy[obs_code]
                    else:
                        return[]
                    
                    self.bird_dict[obs_code] = ObservationData(obs_code, common_name, obs_count, obs_timesince, 1)

        # Converts the time_since attribute back to days; seconds are initially used for accurate sight comparisons
        for t in self.bird_dict.values():
            t.time_since = int(t.time_since // 86400)
            
        # Format observations alphabetically by ObservationData class common name attribute
        self.bird_dict = dict(sorted(self.bird_dict.items(), key=lambda item: item[1].common_name))
        return(self.bird_dict)
