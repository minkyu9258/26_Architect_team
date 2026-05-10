from fastapi import FastAPI

app = FastAPI(title='github-agent', version='0.1.0')

@app.post('/execute')
async def execute(payload: dict):
    task = payload.get('task', {})
    action = task.get('payload', {}).get('action', 'unknown')
    return {
        'success': True,
        'output': {
            'message': f"GitHub agent executed {action}",
            'session_id': payload.get('session_id'),
        }
    }
