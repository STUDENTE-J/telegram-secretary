#!/usr/bin/env python3
"""
Helper script to generate SESSION_DATA for Railway deployment.
Converts secretary_session.session to base64 for environment variable.
"""

import base64
import os
import sys

def generate_session_data():
    session_file = "secretary_session.session"
    
    if not os.path.exists(session_file):
        print(f"❌ Session file not found: {session_file}")
        print("\n📋 To generate the session file:")
        print("   1. Make sure you have a .env file with your credentials")
        print("   2. Run: python main.py")
        print("   3. Complete the Telegram authentication (phone code, 2FA)")
        print("   4. The session file will be created")
        print("   5. Then run this script again")
        return
    
    try:
        # Read session file
        with open(session_file, "rb") as f:
            session_bytes = f.read()
        
        # Encode to base64
        encoded = base64.b64encode(session_bytes).decode('utf-8')
        
        print("✅ SESSION_DATA generated successfully!")
        print("\n📋 Copy this value and set it as SESSION_DATA in Railway:")
        print("-" * 60)
        print(encoded)
        print("-" * 60)
        print("\n💡 In Railway:")
        print("   1. Go to your service → Variables")
        print("   2. Add new variable: SESSION_DATA")
        print("   3. Paste the value above")
        print("   4. Save")
        
        # Also save to file for easy copy
        with open("SESSION_DATA.txt", "w") as f:
            f.write(encoded)
        print("\n💾 Also saved to SESSION_DATA.txt for easy copy")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_session_data()
