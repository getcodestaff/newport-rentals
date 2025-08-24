import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase client initialized")
    except Exception as e:
        print(f"❌ Failed to initialize Supabase client: {e}")
        supabase = None
else:
    print("⚠️ Supabase credentials not found")
    print(f"🔧 SUPABASE_URL: {'SET' if SUPABASE_URL else 'NOT SET'}")
    print(f"🔧 SUPABASE_KEY: {'SET' if SUPABASE_KEY else 'NOT SET'}") 

def get_supabase_client():
    """Get the Supabase client instance"""
    return supabase