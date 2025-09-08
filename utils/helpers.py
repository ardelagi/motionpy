import discord
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import re

def format_playtime(seconds: int) -> str:
    """Format playtime seconds to readable string"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"

def format_ping(ping: float) -> str:
    """Format ping value with color indication"""
    if ping < 50:
        return f"🟢 {ping:.0f}ms"
    elif ping < 100:
        return f"🟡 {ping:.0f}ms"
    else:
        return f"🔴 {ping:.0f}ms"

def get_ping_color(ping: float) -> discord.Color:
    """Get Discord color based on ping value"""
    if ping < 50:
        return discord.Color.green()
    elif ping < 100:
        return discord.Color.yellow()
    else:
        return discord.Color.red()

def sanitize_player_name(name: str) -> str:
    """Sanitize player name for database storage"""
    # Remove special characters and limit length
    sanitized = re.sub(r'[^\w\s-]', '', name)
    return sanitized[:50].strip()

def calculate_percentage(value: float, total: float) -> float:
    """Calculate percentage safely"""
    if total == 0:
        return 0.0
    return (value / total) * 100

def format_timestamp(timestamp: datetime) -> str:
    """Format timestamp to readable string"""
    now = datetime.now()
    diff = now - timestamp
    
    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"

def create_progress_bar(current: int, maximum: int, length: int = 10) -> str:
    """Create a progress bar string"""
    if maximum == 0:
        return "░" * length
    
    filled = int((current / maximum) * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"{bar} {current}/{maximum}"

def parse_identifiers(identifiers: List[str]) -> Dict[str, str]:
    """Parse FiveM player identifiers"""
    parsed = {}
    for identifier in identifiers:
        if ':' in identifier:
            key, value = identifier.split(':', 1)
            parsed[key] = value
    return parsed

def is_valid_player_name(name: str) -> bool:
    """Validate player name format"""
    if not name or len(name) < 3 or len(name) > 50:
        return False
    
    # Check for valid characters (letters, numbers, spaces, hyphens, underscores)
    return bool(re.match(r'^[a-zA-Z0-9\s_-]+$', name))

def get_role_emoji(role: str) -> str:
    """Get emoji for player role"""
    role_emojis = {
        'admin': '👑',
        'moderator': '🛡️',
        'vip': '⭐',
        'police': '👮',
        'ems': '🚑',
        'mechanic': '🔧',
        'civilian': '👤',
        'default': '👤'
    }
    return role_emojis.get(role.lower(), role_emojis['default'])

def get_job_emoji(job: str) -> str:
    """Get emoji for player job"""
    job_emojis = {
        'police': '👮‍♂️',
        'sheriff': '🤠',
        'ems': '🚑',
        'fire': '🚒',
        'mechanic': '🔧',
        'taxi': '🚕',
        'trucker': '🚛',
        'lawyer': '⚖️',
        'judge': '👨‍⚖️',
        'doctor': '👨‍⚕️',
        'unemployed': '❌',
        'civilian': '👤'
    }
    return job_emojis.get(job.lower(), '💼')

def create_embed_template(title: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    """Create a standard embed template"""
    embed = discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.now()
    )
    embed.set_footer(text="Motionlife Roleplay", icon_url="https://i.imgur.com/your-server-icon.png")
    return embed

def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def calculate_uptime_percentage(total_checks: int, successful_checks: int) -> float:
    """Calculate server uptime percentage"""
    if total_checks == 0:
        return 0.0
    return (successful_checks / total_checks) * 100

def get_time_ago(timestamp: datetime) -> str:
    """Get human-readable time ago string"""
    now = datetime.now()
    delta = now - timestamp
    
    if delta.days > 365:
        years = delta.days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
    elif delta.days > 30:
        months = delta.days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    elif delta.days > 0:
        return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
    elif delta.seconds > 3600:
        hours = delta.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif delta.seconds > 60:
        minutes = delta.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"

def validate_config_values(config_dict: Dict[str, Any]) -> List[str]:
    """Validate configuration values and return list of errors"""
    errors = []
    
    required_fields = ['DISCORD_TOKEN', 'MONGODB_URI', 'FIVEM_BASE_URL']
    for field in required_fields:
        if not config_dict.get(field):
            errors.append(f"Missing required field: {field}")
    
    # Validate channel IDs
    channel_fields = ['LEADERBOARD_CHANNEL_ID', 'NOTIFICATIONS_CHANNEL_ID']
    for field in channel_fields:
        value = config_dict.get(field)
        if value and not isinstance(value, int):
            errors.append(f"Invalid {field}: must be an integer")
    
    return errors
