import prng
import re
from datetime import datetime, timedelta, timezone, UTC
import time
import struct
import requests
from io import BytesIO
import hashlib

def read_null_terminated_string(file, encoding='utf-8', return_is_corrupt=False):
    chars = []
    null_char = b'\x00' if encoding != 'utf-16' else b'\x00\x00'

    while True:
        char = file.read(2 if encoding == 'utf-16' else 1)
        if not char or char == null_char:
            break
        chars.append(char)

    byte_data = b''.join(chars)
    is_corrupt = encoding == 'utf-8' and check_encoding_bytes(byte_data)

    try:
        result = byte_data.decode(encoding)
    except:
        try:
            result = byte_data.decode('cp1252')
        except:
            result = byte_data.decode('latin-1')

    return (result, is_corrupt) if return_is_corrupt else result


def check_encoding_bytes(input_bytes):
    try:
        decoded_content = input_bytes.decode('utf-8')
        encoded_bytes = decoded_content.encode('utf-8')
        if input_bytes != encoded_bytes:
            return True
        else:
            return False
    except UnicodeDecodeError:
        return True
    except Exception as e:
        print(f"Error occurred: {e}")
        return None


def is_valid_utf8(byte_string):
    try:
        byte_string.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def hex_to_decimal(hex_string):
    int_value = int.from_bytes(bytes.fromhex(hex_string), byteorder='little')
    return int_value


def assign_random_faction(game_prng, total_factions, game_sd):
    discard = game_sd % 7
    for _ in range(discard):
        game_prng.get_value(0, 1)  # Discard values to improve randomness

    faction_index = game_prng.get_value(0, 1000) % total_factions
    return faction_index


def assign_random_color(game_prng, total_colors, taken_colors):
    color_index = -1
    while color_index == -1:
        random_color = game_prng.get_value(0, total_colors - 1)
        if not taken_colors[random_color]:
            color_index = random_color
            taken_colors[random_color] = True
    return color_index


def ddhhmmss(seconds):
    if seconds == 0:
        return ''
    
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    int_secs = int(secs)
    frames = int((secs - int_secs) * 30)
    
    if days:
        return f"{int(days):02}:{int(hours):02}:{int(minutes):02}:{int_secs:02}.{frames:02}"
    if hours:
        return f"{int(hours):02}:{int(minutes):02}:{int_secs:02}.{frames:02}"
    if minutes:
        return f"{int(minutes):02}m {int_secs:02}s {frames:02}f"
    return f"{int_secs:02}s {frames:02}f"


def get_replay_data(filename, mode):
    """Mode 1: local repay file, Mode 2: online replay file"""
    if mode==1:
        with open(filename, 'rb') as f:
            header, data = parse_replay_data(f)
    elif mode==2:
        response = requests.get(filename)
        if response.status_code == 200:
            with BytesIO(response.content) as f:
                header, data = parse_replay_data(f)
        else:
            # print("Failed to retrieve the file:", response.status_code)
            pass
    return header, data


def parse_replay_data(f):
    """Well, actually just parse the header and return it along with the rest."""
    magic = f.read(6)
    if magic != b'GENREP':
        # print("Not a GENREP file!")
        return
    begin_timestamp, end_timestamp, replay_duration = struct.unpack('<III', f.read(12))
    desync, early_quit = struct.unpack('<BB', f.read(2))
    disconnect = struct.unpack('<8B', f.read(8))
    file_name = read_null_terminated_string(f, encoding='utf-16')
    system_time = struct.unpack('<8H', f.read(16))
    version = read_null_terminated_string(f, encoding='utf-16')
    build_date = read_null_terminated_string(f,encoding='utf-16')
    version_minor, version_major = struct.unpack('<HH', f.read(4))
    exe_crc, ini_crc = struct.unpack('<II', f.read(8))
    match_data, is_corrupt  = read_null_terminated_string(f, return_is_corrupt=True)
    local_player_index = read_null_terminated_string(f)
    difficulty, original_game_mode, rank_points, max_fps = struct.unpack('<iiii', f.read(16))
    data = f.read().hex()

    header =  {
        "magic": magic,
        "begin_timestamp": begin_timestamp,
        "end_timestamp": end_timestamp,
        "replay_duration": replay_duration,
        "desync": desync,
        "early_quit": early_quit,
        "disconnect": disconnect,
        "file_name": file_name,
        "system_time": system_time,
        "version": version,
        "build_date": build_date,
        "version_minor": version_minor,
        "version_major": version_major,
        "exe_crc": exe_crc,
        "ini_crc": ini_crc,
        "match_data": match_data,
        "local_player_index": int(local_player_index),
        "difficulty": difficulty,
        "original_game_mode": original_game_mode,
        "rank_points": rank_points,
        "max_fps": max_fps,
        "is_corrupt": is_corrupt,
    }

    return header, data


def fix_empty_slot_issue(slots_data):
    initial_indices = {}
    occupied_idx = 0
    for i, slot in enumerate(slots_data):
        if slot not in {'X', 'O'}:
            initial_indices[i] = occupied_idx
            occupied_idx += 1
    return initial_indices


def get_pl_num_offset(player_slot, slots_data, hex_data):
    """Player num usually starts at 2, however for some maps this is not the case (eg. casino maps), we assume
    that the slot number will tell us this replay's player. If the replay ended properly then we could use the
    final message and slot number to get the offset. However, if the slot number is wrong or is manipulated/corrupt?, 
    we would get wrong offset values, so well shall first look for the player number using the first logic crc
    check, and then use other methods if that fails"""
    fixed_slots = fix_empty_slot_issue(slots_data)
    
    offset = 2
    pl_num_from_first_crc = []
    index_of_first_crc = hex_data.find("00470400000")
    if index_of_first_crc != -1:
        frame_hex = hex_data[index_of_first_crc-6:index_of_first_crc+2]
        first_check = set(re.findall(f"{frame_hex}470400000.", hex_data))
        
        if first_check and len(first_check)>1:
            for ck in sorted(first_check):
                pl_num_from_first_crc.append(int(ck[-1], 16))
        if len(pl_num_from_first_crc) == len(fixed_slots):
            offset = pl_num_from_first_crc[0]
            num_player = offset + fixed_slots[player_slot]
            
            if hex_data[-18:-10] == '1b000000':
                if num_player != int(hex_data[-9:-8], 16):
                    # print('Wrong slot in rep.')
                    #since there are cases where slot is wrong, take the num_player from the clear replay message at the end.
                    num_player = int(hex_data[-9:-8], 16)
                return num_player, offset, True
            else:
                return num_player, offset, False
    
    if pl_num_from_first_crc:
        offset = pl_num_from_first_crc[0]
        if hex_data[-18:-10] == '1b000000':
            num_player = int(hex_data[-9:-8], 16)
            offset = num_player - fixed_slots[player_slot]
            return num_player, offset, True

    # if no logic crc was found, the replay ended in dc at start, so it dosen't matter.  
    num_player = offset + fixed_slots[player_slot]
    return num_player, offset, False


def comp_name(comp):
    if comp == 'E':
        return 'Easy AI'
    elif comp == 'M':
        return 'Medi AI'
    elif comp == 'H':
        return 'Hard AI'


def fix_teams(teams, players):
    if 0 in teams:
        taken_keys = set(teams.keys())
        new_team_keys = [key for key in range(1, max(taken_keys) + len(teams[0]) + 1) if key not in taken_keys]
        players_without_team = teams.pop(0, [])
        for player in players_without_team:
            new_team_key = new_team_keys.pop(0)
            teams[new_team_key] = [player]
            players[player]['team'] = new_team_key
        teams = dict(sorted(teams.items()))
        return teams, players
    else:
        teams = dict(sorted(teams.items()))
        return teams, players


def get_match_type(teams):
    match_type = 'v'.join(map(str, sorted(len(players) for players in teams.values())))
    return match_type


def find_winning_team(teams_data):
    teams_remain = []
    teams_quit = []
    found_winner = False
    winning_team = 0
    for team, player_times in teams_data.items():
        if -1 in player_times:
            if teams_remain:
                return found_winner, winning_team
            teams_remain.append(team)
        else:
            teams_quit.append((team, max(player_times)))
    if teams_remain:
        found_winner = True
        return found_winner, teams_remain[0]
    else:
        if teams_quit:
            found_winner = True
            return found_winner, max(teams_quit, key=lambda x: x[1])[0]
        else:
            return found_winner, winning_team


def extract_frame(hex_data, index):
    """Extract frame value at given message index in replay."""
    return hex_to_decimal(hex_data[index-8:index])


def extract_crc(hex_data, index):
    """Extract CRC value at given crc message index in replay."""
    return hex_to_decimal(hex_data[index+34:index+44])


def update_players_data(num_player, hex_data, quit_data, teams, teams_data, winning_team, players_quit_frames, 
                        observer_num_list, last_crc_data, last_crc_index, found_winner):
    # Cache frame time where victory occurs if it exists
    if found_winner and len(teams)>1:
        max_losers_index = max([max(times) for team, times in teams_data.items() if team != winning_team])

    for player_num in players_quit_frames:
        player_data = players_quit_frames[player_num]
        
        # Add CRC data if available and applicable
        if player_num in last_crc_data:
            # Check if we should add CRC
            crc_condition = ((player_num not in quit_data and num_player not in quit_data) or 
                            (player_num in quit_data and len(quit_data[player_num])==1 and last_crc_index > quit_data[player_num][0]
                                and (num_player not in quit_data or last_crc_index > quit_data[num_player][0]) ) or
                            (player_num not in quit_data and num_player in quit_data and last_crc_index > quit_data[num_player][0]))
                            
            if crc_condition:
                player_data['last_crc'] = extract_crc(hex_data, last_crc_data[player_num])
    
    for player_num in players_quit_frames:  
        player_data = players_quit_frames[player_num]  
        
        # Skip players without quit data
        if player_num not in quit_data:
            continue
            
        quit_indices = quit_data[player_num]
        
        # Handle multiple quit events (always surrender then exit)
        if len(quit_indices) > 1:
            player_data['surrender'] = extract_frame(hex_data, quit_indices[0])
            player_data['exit'] = extract_frame(hex_data, quit_indices[1])
            continue
            
        # Handle single quit event
        frame_time = extract_frame(hex_data, quit_indices[0])
        
        # Observer can only exit
        if player_num in observer_num_list:
            player_data['exit'] = frame_time
            continue
            
        # Players that surrender only still continue sending logic crc checks.
        if player_num in last_crc_data and last_crc_index > quit_indices[0]:
            player_data['surrender'] = frame_time
            continue
            
        # Special handling for comparing to num_player
        if player_num != num_player and num_player in quit_data:

            # Winning players at the end can only exit
            if (found_winner) and (player_num in teams[winning_team]):
                if quit_indices[0] > max_losers_index:
                    player_data['exit'] = frame_time
                    continue

            # Exit since player was not found in the next crc check?
            if players_quit_frames[num_player]['last_crc'] == '':
                # this replay's player did not stay till the end.
                crc_index_before_quit = hex_data.rfind(f"470400000{num_player:x}0000000200010201", 0, quit_data[num_player][0])
                crc_frame_before_quit = hex_data[crc_index_before_quit-8:crc_index_before_quit]

                if frame_time < hex_to_decimal(crc_frame_before_quit):
                    if hex_data.rfind(f"{crc_frame_before_quit}470400000{player_num:x}0000000200010201") != -1:
                        # if player_num quit before this replay's player(num_player) and then was part of a crc check before num_player quit.
                        player_data['surrender'] = frame_time
                    else:
                        # else player exited
                        player_data['exit'] = frame_time
                else:
                    # if no crc check after player_num quit and before this replay's player quit, its surrender or exit (we don't know which)
                    player_data['surrender/exit?'] = frame_time
            elif players_quit_frames[num_player]['last_crc'] != '':
                if player_data['last_crc'] == '':
                    player_data['exit'] = frame_time
                else:
                    player_data['surrender'] = frame_time

            continue
            
        player_data['exit'] = frame_time


def get_match_mode(host_hex_ip, host_port):
    host_hex_ip_dec = int(host_hex_ip, 16)
    try:
        host_hex_ip_dec = int(host_hex_ip, 16)
    except ValueError:
        return 'Invalid IP'
    
    lan_ranges = [
        ('1A000000', '1AFFFFFF', 'LAN (Radmin)'),
        ('19000000', '19FFFFFF', 'LAN (Hamachi)'),
        ('C0A80000', 'C0A8FFFF', 'LAN'),
        ('0A000000', '0AFFFFFF', 'LAN'),
        ('AC100000', 'AC1FFFFF', 'LAN'),
        ('A9FE0000', 'A9FEFFFF', 'LAN'),
        ('07000000', '07FFFFFF', 'LAN')
    ]
    
    if host_port == '8088':
        for start, end, mode in lan_ranges:
            if int(start, 16) <= host_hex_ip_dec <= int(end, 16):
                return mode
        return 'GameRanger'
    
    if host_hex_ip_dec == 0 and host_port == '0':
        return 'Skirmish Mode'
    
    return 'Online'


def ordinal(n):
    if n == 0:
        return ""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def sanitize_filename(filename, replacement="_"):
    # Windows reserved characters that are not allowed in filenames
    invalid_chars = r'[<>:"/\\|?*]'

    # Remove invalid characters and trim leading/trailing spaces or dots
    cleaned = re.sub(invalid_chars, replacement, filename).strip(" .")

    return cleaned


def string_to_md5(input_string):
    return hashlib.md5(input_string.encode()).hexdigest()


def get_match_id(url, start_time, game_sd, match_type, map_crc, player_nicks):
    """Generate a match id that can be used to uniquely identify all replays of the same game. Useful for those looking 
    to to scrap and merge match info for analysis or a leaderboard.
    """
    # Shatabrick uses the hex of <yyyy-dd-mm><game_sd>, however since the game seed is generated from GetTickCount()
    # there's a risk of collisions. Therefore, based on sample data scrapped from gt for 2 days, perhaps a better way to 
    # generate the match id would be by additionally using the match type, map crc and player names(as long as they are 
    # not corrupt). Player IPs were not used here as there are cases where they are not the same for the same game replay. 

    date_in_replay = datetime.fromtimestamp(start_time, UTC).date()
    date_uploaded = date_in_replay

    # Extract date from URL (use the server date when file was uploaded)
    match = re.search(r'/(\d{4})_(\d{2})_[^/]+/(\d{2})_', url)
    if match:
        year, month, day = map(int, match.groups())
        date_uploaded = datetime(year, month, day).date()

    yesterday = date_uploaded - timedelta(days=1)
    two_days_ago = date_uploaded - timedelta(days=2)

    # Allow date_in_replay to date back up to 2 days prior to the date_uploaded, else use the date_uploaded.
    if (date_in_replay == yesterday) or (date_in_replay == two_days_ago):
        return string_to_md5(f"{date_in_replay.strftime('%Y%m%d')}{game_sd}{match_type}{map_crc}{''.join(player_nicks)}")
    else:
        return string_to_md5(f"{date_uploaded.strftime('%Y%m%d')}{game_sd}{match_type}{map_crc}{''.join(player_nicks)}")


def get_replay_info(file_path, mode, rename_info=False):
    header, hex_data = get_replay_data(file_path, mode)

    start_time = header['begin_timestamp']
    end_time = header['end_timestamp']
    rep_duration = header['replay_duration']
    player_slot = header['local_player_index']

    desync = header['desync']
    disconnect = header['disconnect']
    exe_match = 3660270360
    ini_match = 4272612339
    exe_check = "Success" if header['exe_crc'] == exe_match else "Failed"
    ini_check = "Success" if header['ini_crc'] == ini_match else "Failed"
    version = header['version']
    match_data = {}

    # Split the string into parts using ';'
    parts = header['match_data'][:-2].split(';')

    # Initialize result list and a string to collect the rest
    parts_list = []
    rest_of_string = ""

    # Iterate through parts to collect until "S=H"
    # Usually players cant use ';' in their name, but we still handle it here, just incase.
    for part in parts:
        if part.startswith('S=H'):
            # Once we encounter "S=H", collect the rest of the string
            rest_of_string = ';'.join(parts[parts.index(part):])
            break
        parts_list.append(part)

    # Append the rest of the string as one element
    parts_list.append(rest_of_string)

    for part in parts_list:
        key_value = part.split('=', maxsplit=1)
        if len(key_value) == 2:
            key, value = key_value
            match_data[key] = value

    # Usually players cant use ':' in their name, but we still handle it here, just incase.
    slots_data = re.split(r':(?=[HCXO])', match_data.get('S', ''))

    map_crc = match_data.get('MC', 'Unknown')
    map_name = match_data.get('M', 'Unknown')
    if map_name != 'Unknown':
        map_name = map_name[map_name.rfind('/')+1:]
    # map_size = match_data.get('MS', 'Unknown')
    game_sd = int(match_data.get('SD', 'Unknown'))
    crc_interval = match_data.get('C', 'Unknown')
    sw_restriction = match_data.get('SR', 'Unknown')
    if sw_restriction == '0':
        sw_restriction = 'Yes'
    elif sw_restriction == '1':
        sw_restriction = 'No'
    else:
        sw_restriction = 'Unknown'
    start_cash = match_data.get('SC', 'Unknown')
    # old_factions = match_data.get('O', 'Unknown')

    num_player, offset, is_normal_rep = get_pl_num_offset(player_slot, slots_data, hex_data)

    actual_replay_end = rep_duration
    actual_end_frame = 0

    if not is_normal_rep:
        # if game is aborted or crashed, game frame is not stored in header, so try to get it from the last message.
        last_messages = re.findall(r"00....00000.0000000", hex_data[-1000:])
        if len(last_messages) >= 1:
            index = hex_data.rfind(last_messages[-1])
            actual_end_frame = hex_to_decimal(hex_data[index-6:index+2])
            actual_replay_end = actual_end_frame
            rep_duration = actual_replay_end

    players = {}
    teams = {}

    colors = {
        -1: 'Random',
        0: 'Gold', 
        1: 'Red', 
        2: 'Blue', 
        3: 'Green', 
        4: 'Orange', 
        5: 'Cyan', 
        6: 'Purple', 
        7: 'Pink'
    }
    factions = {
        -2: 'Observer',
        -1: 'Random',
        0: 'USA', 
        1: 'China', 
        2: 'GLA', 
        3: 'USA Superweapon', 
        4: 'USA Laser', 
        5: 'USA Airforce', 
        6: 'China Tank', 
        7: 'China Infantry', 
        8: 'China Nuke', 
        9: 'GLA Toxin', 
        10: 'GLA Demolition', 
        11: 'GLA Stealth'
    }

    computer_player_in_game = False
    player_num_list = []
    observer_num_list = []
    pl_count = 0
    player_nicks = []
    for index, player_raw in enumerate(slots_data):
        if (player_raw == 'X') or (player_raw == 'O'):
            continue
        player_data = player_raw.split(',')
        if player_data[0][0] == 'H':
            if index == 0:
                host_hex_ip = player_data[1]
                host_port = player_data[2]
            
            players[pl_count+offset] = {
                'name': player_data[0][1:],
                'ip': player_data[1],
                'port': int(player_data[2]),
                # 'is_accepted': player_data[3][0],
                # 'has_map': player_data[3][1],
                'color': int(player_data[4]),
                'faction': int(player_data[5]),
                'start_pos': int(player_data[6]),
                'team': int(player_data[7])+1,
                # 'nat_behavior': int(player_data[8]),
                'dc': disconnect[index],
                'random': 0,
            }

            pl_nick = player_data[0][1:]
            if header['is_corrupt']:
                try:
                    if not is_valid_utf8(pl_nick.encode('latin-1')):
                        pl_nick = 'player'
                except:
                    pl_nick = 'player'
            player_nicks.append(pl_nick)
            
            players[pl_count+offset]['random'] = 1 if players[pl_count+offset]['faction'] == -1 else 0
            
            if int(player_data[5]) != -2:
                if (int(player_data[7])+1) not in teams:
                    teams[int(player_data[7])+1] = []
                teams[int(player_data[7])+1].append(pl_count+offset)
                player_num_list.append(pl_count+offset)
            else:
                observer_num_list.append(pl_count+offset)
            pl_count += 1

        elif player_data[0][0] == 'C':
            computer_player_in_game = True
            
            player_num_list.append(pl_count+offset)
            players[pl_count+offset] = {
                'name': comp_name(player_data[0][1:]),
                'ip': '',
                'port': '',
                # 'is_accepted': '',
                # 'has_map': '',
                'color': int(player_data[1]),
                'faction': int(player_data[2]),
                'start_pos': int(player_data[3]),
                'team': int(player_data[4])+1,
                # 'nat_behavior': '',
                'dc': disconnect[index],
                'random': 0,
            }

            player_nicks.append(comp_name(player_data[0][1:]))
            players[pl_count+offset]['random'] = 1 if players[pl_count+offset]['faction'] == -1 else 0
            
            if int(player_data[2]) != -2:
                if (int(player_data[4])+1) not in teams:
                    teams[int(player_data[4])+1] = []
                teams[int(player_data[4])+1].append(pl_count+offset)
            # else:
            #     observer_num_list.append(pl_count+offset)
            pl_count += 1

    game_prng = prng.RandomGenerator(game_sd)
    total_colors = 8
    total_factions = 12

    if (sw_restriction == 'Unknown') and start_cash == ('Unknown'):
        #probably a generals replay.
        total_factions = 3

    taken_colors = [False]*total_colors
    for key, value in players.items():
        if (value['color'] != -1) and (value['color'] < total_colors):
            taken_colors[value['color']] = True

    for key, value in players.items():
        if value['faction'] == -1:
            faction_index = assign_random_faction(game_prng, total_factions, game_sd)
            value['faction'] = faction_index
        elif value['faction'] > 0:
            value['faction'] = value['faction']-2
        if value['color'] == -1:
            color_index = assign_random_color(game_prng, total_colors, taken_colors)
            value['color'] = color_index

    teams, players = fix_teams(teams, players)
    match_type = get_match_type(teams)
    
    rename_factions = {
        -2: 'obs', 
        -1: 'random', 
        0 : 'usa', 
        1: 'china', 
        2: 'gla', 
        3: 'sw', 
        4: 'laser', 
        5: 'air', 
        6: 'tank', 
        7: 'inf', 
        8: 'nuke', 
        9: 'tox', 
        10: 'demo', 
        11: 'stealth'
    }
    

    if rename_info == True:
        teams_filename = []

        for key, value in teams.items():
            teams_filename_string = ''
            for val in value:
                teams_filename_string += f"{players[val]['name']}({rename_factions[players[val]['faction']]}) "
            teams_filename.append(teams_filename_string)

        teams_filename_string = 'vs '.join(teams_filename).strip()
        return sanitize_filename(f"{match_type} [{datetime.fromtimestamp(start_time, UTC).strftime("%y.%m.%d")}] ({map_name}) {teams_filename_string}")

    quit_data = {} #store self_destruct message indices
    for match in re.finditer(r'450400000.000000010201', hex_data):
        match_str = int(match.group(0)[9:10], 16)
        if match_str in quit_data:
            quit_data[match_str].append(match.start())
        else:
            quit_data[match_str] = [match.start()]        

    #store self_destruct message indices (the first occurence) with team details
    teams_data = {team: [quit_data.get(player, [-1])[0] for player in players] for team, players in teams.items()}

    last_crc_data = {} #store last crc message indices 
    last_crc_index = hex_data.rfind(f"470400000{num_player:x}0000000200010201")
    last_crc_frame = 0
    last_crc = 0
    if last_crc_index != -1:
        last_crc_frame = hex_data[last_crc_index-8:last_crc_index]
        last_crc = hex_data[last_crc_index+26:last_crc_index+26+8]
        for match in re.finditer(f'{last_crc_frame}470400000.0000000200010201', hex_data):
            match_str = int(match.group(0)[17:18], 16)
            last_crc_data[match_str] = match.start()

    players_quit_frames = {key: {} for key in players}
    for key, value in players.items():
        players_quit_frames[key]['surrender'] = 0
        players_quit_frames[key]['exit'] = 0
        players_quit_frames[key]['last_crc'] = ''
        players_quit_frames[key]['surrender/exit?'] = 0
        players_quit_frames[key]['idle/kicked?'] = 0

    found_winner, winning_team = find_winning_team(teams_data)

    update_players_data(num_player, hex_data, quit_data, teams, teams_data, winning_team, players_quit_frames, observer_num_list, last_crc_data, last_crc_index, found_winner)

    player_final_message_frame = actual_replay_end
    if num_player in quit_data:
        if len(quit_data[num_player]) == 1:
            if players_quit_frames[num_player]['surrender'] == 0:
                if players_quit_frames[num_player]['exit'] != 0:
                    player_final_message_frame = players_quit_frames[num_player]['exit']
                elif players_quit_frames[num_player]['surrender/exit?'] != 0:
                    player_final_message_frame = players_quit_frames[num_player]['surrender/exit?']
        else:
            player_final_message_frame = players_quit_frames[num_player]['exit']
    else:
        if last_crc_index != -1:
            player_final_message_frame = hex_to_decimal(hex_data[last_crc_index-8:last_crc_index])
    

    #typical messages (orders) that observer players can also send (needs updating). 
    #pattern: 00xxxxxxxx0 (messages are 4 bytes only but we include msb of frame and first 4bits of player num, as they are always 0, to imporve search)
    patterns = ["001b0000000", "00470400000", "00490400000", "00eb0300000", "00e90300000", "00220400000", "00450400000", "00f80300000", "00f90300000", "00fa0300000", "00fb0300000", "00fc0300000", "00fd0300000", "00fe0300000", "00ff0300000", "00000400000", "00010400000", ]

    #look for idle players that most likely got kicked (needs more testing). Note: Frame(timestamp) will not necessarily correspond to the moment of kick, but around that time depending on the scenario (Eg. player has useless last buildings and is just hiding and waiting to be kicked, actual kick cold be way later, but will be considered idle the moment the player cant really impact others in the game (this might impact placement results)). 
    update_players_data_again = False
    idle_kick_index = []
    if player_final_message_frame >= 5400: #if replay is greater than 3 minutes
        for key, value in players_quit_frames.items():
            if (key not in observer_num_list):
                if (value['surrender'] == 0) or (key not in quit_data):
                    if player_final_message_frame >= 2111:
                        
                        pl_msges = re.findall(f'00....00000{key:x}000000', hex_data)
                        pl_msges = [s for s in pl_msges if not any(s.startswith(pattern) for pattern in patterns)]
                        if len(pl_msges) >=1:
                            for msg in reversed(pl_msges):
                                if int(msg[11:12], 16) == key:
                                    msg_index = hex_data.rfind(msg)
                                    msg_frame = hex_to_decimal(hex_data[msg_index-6: msg_index+2])

                                    if found_winner:
                                        diff = 900
                                    else:
                                        diff = 1800
                                    
                                    if (player_final_message_frame - msg_frame) >=900:
                                        if (value['exit'] != 0) and ((value['exit'] - msg_frame) >= 1200):
                                            value['idle/kicked?'] = msg_frame
                                            quit_data[key].insert(0, msg_index+2)
                                            idle_kick_index.append(msg_index+2)
                                            update_players_data_again = True
                                        elif (value['surrender/exit?'] != 0) and ((value['surrender/exit?'] - msg_frame) >= 1800):
                                            value['idle/kicked?'] = msg_frame
                                            quit_data[key].insert(0, msg_index+2)
                                            idle_kick_index.append(msg_index+2)
                                            update_players_data_again = True
                                        elif (key not in quit_data) and (player_final_message_frame-msg_frame >= diff):
                                            value['idle/kicked?'] = msg_frame
                                            quit_data[key] = [msg_index+2]
                                            idle_kick_index.append(msg_index+2)
                                            update_players_data_again = True
                                    break

    
    if update_players_data_again:
        teams_data = {team: [quit_data.get(player, [-1])[0] for player in players] for team, players in teams.items()}
        found_winner, winning_team = find_winning_team(teams_data)
        for key, value in players.items():
            if players_quit_frames[key]['idle/kicked?']!=0:
                if players_quit_frames[key]['surrender/exit?']!=0:
                    players_quit_frames[key]['exit'] = players_quit_frames[key]['surrender/exit?']
                    players_quit_frames[key]['surrender/exit?'] = 0
        
    match_result = ''
    winning_team_string = ''

    if (desync == 1 and found_winner): #sometimes desync occurs at the end of the game?
        winning_team_string = f"{winning_team}"
    elif desync == 1:
        found_winner = False
        match_result = 'Desync'
        winning_team_string = 'No Result (Desync)'
    elif computer_player_in_game:
        found_winner = False
        match_result = 'No Result (No data from computer player)'
        winning_team_string = 'No Result (No data from computer player)'
    elif len(teams) == 1:
        found_winner = False
        match_result = 'No Result (No opponents)'
        winning_team_string = 'No Result (No opponents)'

    if found_winner:
        winning_team_string = winning_team

        # frame time where victory occurs
        game_end_quit_index = max([max(times) for team, times in teams_data.items() if team != winning_team])

        # if argument of self_destruct msg command is false, means a vote/countdown kick occured.
        # (eg in 1v1 both players replay would declare them as winners if this was not taken into account, 
        # because both would store the other as vote/countdown kicked.)
        if game_end_quit_index not in idle_kick_index:
            if int(hex_data[game_end_quit_index+22:game_end_quit_index+24], 16) == 0: 
                match_result = 'Ended in Disconnect Menue with a player vote/countdown kick'
                winning_team_string = 'Unknown (DC)'
                found_winner = False


        if found_winner:            
            #if there is a winner, update players match result to win or loss
            if num_player in player_num_list:
                if num_player in teams[winning_team]:
                    match_result = f'Win'
                else:
                    match_result = f'Loss'                       
            elif num_player in observer_num_list:
                match_result = f'Team {winning_team} won'

    elif match_result=='':
        # Pattern 1
        # destroy selected group messages of the remaining players in order once, then logic crc messages of the remaining players in order once.
        # Pattern 2
        # destroy selected group messages of the remaining players in order once, then logic crc messages of the remaining players in order twice.
        # Pattern 3
        # logic crc messages of the remaining players in order once, then destroy selected group messages of the remaining players in order once.


        winning_team_string = 'Unknown'
        found_winner = False
        # check if game ended without any surrender or exit from all the remaining players. (Based on patterns found in 1v1 games which generalizes to all format)
        if last_crc_index != -1:

            second_last_crc_index = hex_data.rfind(f"470400000{num_player:x}0000000200010201", 0, last_crc_index)

            last_destroy_selected_msgs_string = ''
            last_logic_crc_msgs_string = ''
            seccond_last_logic_crc_msgs_string = ''

            last_destroy_selected_index = hex_data.rfind(f'00eb0300000{num_player:x}00000001020101')
            last_destroy_selected_frame = hex_data[last_destroy_selected_index-6: last_destroy_selected_index+2]

            for pl in players_quit_frames.keys():
                if (players_quit_frames[pl]['exit']==0) and (players_quit_frames[pl]['surrender/exit?']==0):
                    last_destroy_selected_msgs_string += f'{last_destroy_selected_frame}eb0300000{pl:x}00000001020101'
                    last_logic_crc_msgs_string += f'{last_crc_frame}470400000{pl:x}0000000200010201{last_crc}00'
                    if second_last_crc_index != -1:
                        second_last_crc_frame = hex_data[second_last_crc_index-8:second_last_crc_index]
                        second_last_crc = hex_data[second_last_crc_index+26:second_last_crc_index+26+8]
                        seccond_last_logic_crc_msgs_string += f'{second_last_crc_frame}470400000{pl:x}0000000200010201{second_last_crc}00'
                    
            pattern_1 = f'{last_destroy_selected_msgs_string}{last_logic_crc_msgs_string}{hex_data[-26:-18]}1b0000000{num_player:x}00000000'
            pattern_2 = f'{last_destroy_selected_msgs_string}{seccond_last_logic_crc_msgs_string}{last_logic_crc_msgs_string}{hex_data[-26:-18]}1b0000000{num_player:x}00000000'
            pattern_3 = f'{last_logic_crc_msgs_string}{last_destroy_selected_msgs_string}{hex_data[-26:-18]}1b0000000{num_player:x}00000000'

            if hex_data.rfind(pattern_1) != -1:
                match_result = 'Unknown 1'
            elif hex_data.rfind(pattern_2) != -1:
                match_result = 'Unknown 2'
            elif hex_data.rfind(pattern_3) != -1:
                match_result = 'Unknown 3'
    
            if 'Unknown' in match_result:
                last_check_frame = 0
                all_crc = re.findall(f'........470400000{num_player:x}0000000200010201', hex_data)
                if len(all_crc) < 2:
                    last_check_frame = 0
                elif match_result!='Unknown 3' and len(all_crc) >= 3:
                    last_check_frame = all_crc[-3][:8]
                else:
                    last_check_frame = all_crc[-2][:8]
                    
                pl_msges = re.findall('00....00000.000000', hex_data[hex_data.rfind(f"{last_check_frame}470400000"):])
                pl_msges = [s for s in pl_msges if not any(s.startswith(pattern) for pattern in patterns)]
                
                remaining_players = []
                remaining_teams = []
                for x in player_num_list:
                    if x not in quit_data:    
                        remaining_players.append(x)
                        if players[x]['team'] not in remaining_teams:
                            remaining_teams.append(players[x]['team'])

                if pl_msges:
                    win_pl = None
                    for msg in reversed(pl_msges):
                        win_pl = int(msg[11:12], 16)
                        if win_pl in player_num_list:
                            break
                    if (win_pl in player_num_list) and (len(remaining_teams)==2):
                        winning_team = players[win_pl]['team']

                        for key, value in players.items():
                            if (key not in quit_data) and (key not in observer_num_list) and (value['team'] != winning_team ):
                                if hex_to_decimal(last_crc_frame) >= 500:
                                    if match_result == 'Unknown 2':   
                                        players_quit_frames[key]['idle/kicked?'] = hex_to_decimal(last_crc_frame)-300
                                        quit_data[key] = [last_crc_index]
                                        teams_data[value['team']][teams[value['team']].index(key)] = last_crc_index
                                    else:
                                        players_quit_frames[key]['idle/kicked?'] = hex_to_decimal(last_crc_frame)-240
                                        quit_data[key] = [last_crc_index]
                                        teams_data[value['team']][teams[value['team']].index(key)] = last_crc_index
                        if num_player in teams[winning_team]:
                            match_result = f'Win'
                        else:
                            match_result = f'Loss'
                        if num_player in observer_num_list:
                            match_result = f'Team {winning_team} won'
                        winning_team_string = winning_team
                        found_winner = True                        
            else:
                match_result = 'Ended with Quit Game in Disconnect Menu'
                if num_player in player_num_list:
                    if ((players_quit_frames[num_player]['exit']) != 0) and (-1 not in teams_data[players[num_player]['team']]):
                        match_result = 'Loss'
                    elif players_quit_frames[num_player]['exit'] != 0:
                        match_result = 'Unk (Not enough data)'
                    if not is_normal_rep:
                        match_result = 'DC (Game aborted or crashed)'
                elif (num_player in observer_num_list) and (num_player in quit_data):
                    match_result = 'Unk (Not enough data (Obs quit early or before end patterns))'
        else:
            match_result = 'DC at start of game'


    
    placement = {}
    if found_winner:
        actual_replay_end = extract_frame(hex_data, max([max(times) for team, times in teams_data.items() if team != winning_team]))

        other_teams_rank = sorted(
            [(team, max(times)) for team, times in teams_data.items() if team != winning_team],
            key=lambda x: x[1], 
            reverse=True
        )

        # Create a placement dictionary with ranks
        placement = {team: ordinal(rank) for rank, team in enumerate(
            [winning_team] + [team for team, _ in other_teams_rank], start=1)}

    replay_info = [
        ("Start Time (UTC)", time.strftime("%A, %B %d, %Y at %I:%M %p", time.gmtime(start_time))),
        ("Version String", version),
        ("Build Date", header["build_date"]),
        ("EXE check (1.04)", exe_check),
        ("INI check (1.04)", ini_check),
        ("Map Name", map_name),
        ("Start Cash", start_cash),
        ("SW Restriction", sw_restriction),
        ("Match Type", match_type),
        ("Replay Duration", ddhhmmss(actual_replay_end/30)),
        ("Match Mode", get_match_mode(host_hex_ip, host_port)),
        ("Player Name", players[num_player]["name"]),
        # ("Player IP", players[num_player]["ip"]),
        ("Match Result", match_result),
        ("Winning Team", winning_team_string),
        ('Color', colors.get(players[num_player]['color'], 'Unknown')) 
    ]

    if mode == 2:
        replay_info.insert(0, ("Match ID", get_match_id(file_path, start_time, game_sd, match_type, map_crc, player_nicks)))

    player_infos = []
    for key, value in players.items():
        player_infos.append((value['team'], value['ip'], value['name'], f"{factions.get(value['faction'], 'Unknown')} {'(Random)' if value['random']==1 else ''}", ddhhmmss(players_quit_frames[key]['surrender/exit?']/30), ddhhmmss(players_quit_frames[key]['surrender']/30), ddhhmmss(players_quit_frames[key]['exit']/30), ddhhmmss(players_quit_frames[key]['idle/kicked?']/30), players_quit_frames[key]['last_crc'], placement.get(value['team'], ''), colors.get(value['color'], 'Unknown')))

    return replay_info, player_infos
