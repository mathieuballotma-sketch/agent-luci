import subprocess
import re
import platform

def get_system_info():
    info = {}
    info['system'] = platform.system()
    info['machine'] = platform.machine()

    try:
        cpu_brand = subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string']).decode().strip()
        info['cpu_brand'] = cpu_brand
    except Exception:
        info['cpu_brand'] = 'unknown'

    try:
        mem_bytes = subprocess.check_output(['sysctl', '-n', 'hw.memsize']).decode().strip()
        info['ram_gb'] = int(mem_bytes) // (1024**3)
    except Exception:
        info['ram_gb'] = 8

    if 'Apple' in info['cpu_brand'] and 'M' in info['cpu_brand']:
        match = re.search(r'M(\d+)', info['cpu_brand'])
        if match:
            info['chip'] = f"M{match.group(1)}"
        else:
            info['chip'] = 'Apple Silicon'
    else:
        info['chip'] = 'Intel'

    return info

def get_performance_profile(ram_gb, chip):
    if ram_gb >= 32 and chip in ['M3', 'M4']:
        return 'high'
    elif ram_gb >= 16:
        return 'medium'
    else:
        return 'low'

def get_optimized_config():
    info = get_system_info()
    profile = get_performance_profile(info['ram_gb'], info.get('chip', ''))
    config = {
        'profile': profile,
        'chip': info.get('chip', 'unknown'),
        'ram_gb': info['ram_gb'],
    }
    if profile == 'high':
        config['llm'] = {
            'default_model': 'qwen2.5:7b',
            'speed_model': 'qwen2.5:3b',
            'balanced_model': 'qwen2.5:7b',
            'quality_model': 'qwen2.5:14b',
            'sentinel_model': 'qwen2.5:0.5b',
            'max_tokens': 4096,
        }
        config['vision'] = {'interval': 0.5, 'crop': True}
        config['rag'] = {'chunk_size': 1000, 'embedding_model': 'all-MiniLM-L6-v2'}
    elif profile == 'medium':
        config['llm'] = {
            'default_model': 'qwen2.5:3b',
            'speed_model': 'qwen2.5:3b',
            'balanced_model': 'qwen2.5:7b',
            'quality_model': 'qwen2.5:7b',
            'sentinel_model': 'qwen2.5:0.5b',
            'max_tokens': 2048,
        }
        config['vision'] = {'interval': 1.0, 'crop': True}
        config['rag'] = {'chunk_size': 500, 'embedding_model': 'all-MiniLM-L6-v2'}
    else:
        config['llm'] = {
            'default_model': 'qwen2.5:3b',
            'speed_model': 'qwen2.5:3b',
            'balanced_model': 'qwen2.5:3b',
            'quality_model': 'qwen2.5:7b',
            'sentinel_model': 'qwen2.5:0.5b',
            'max_tokens': 1024,
        }
        config['vision'] = {'interval': 2.0, 'crop': True}
        config['rag'] = {'chunk_size': 300, 'embedding_model': 'all-MiniLM-L6-v2'}

    return config