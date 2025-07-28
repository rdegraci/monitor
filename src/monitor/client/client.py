import requests

def main():
    print("Simple Chat Client (HTTP POST mode)")
    server_url = 'http://127.0.0.1:5000/cli'
    print(f"Type your message (or 'exit' to quit). Sending to {server_url}\n")
    
    while True:
        user_input = input('> ').strip()
        if user_input.lower() in {'exit', '/exit', 'quit'}:
            print("Exiting client.")
            break
        
        try:
            response = requests.post(server_url, json={"command": user_input}, timeout=30)
            if response.status_code == 200:
                data = response.json()
                # Show 'result' if present, fall back to 'message' or entire payload
                if 'result' in data:
                    print(data['result'])
                elif 'message' in data:
                    print(data['message'])
                else:
                    print(data)
            else:
                print(f"Error: Server responded with status {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    main()
