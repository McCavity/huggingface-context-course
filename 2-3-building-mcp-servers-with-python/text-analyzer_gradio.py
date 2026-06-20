import gradio as gr
import json

def analyze_text(text: str) -> str:
    """Analyze text and compute statistics.
    
    Args:
        text: The input text to analyze
    
    Returns:
        JSON with analysis results
    """
    words = text.split()
    chars = len(text)
    
    return json.dumps({
        "words": len(words),
        "characters": chars,
        "average_word_length": round(chars / len(words), 2) if words else 0
    })

def reverse_text(text: str) -> str:
    """Reverse a string.
    
    Args:
        text: Input text
    
    Returns:
        The reversed text
    """
    return text[::-1]

def count_vowels(text: str) -> int:
    """Count vowels in text.
    
    Args:
        text: Input text
    
    Returns:
        Number of vowels
    """
    vowels = "aeiouAEIOU"
    return sum(1 for char in text if char in vowels)

# Create interface
with gr.Blocks(title="Text Tools") as demo:
    gr.Markdown("# Text Processing Tools")
    
    with gr.Tab("Analyze Text"):
        text_input1 = gr.Textbox(label="Enter text", lines=5)
        analysis_output = gr.Textbox(label="Analysis", lines=5)
        gr.Button("Analyze").click(analyze_text, text_input1, analysis_output)
    
    with gr.Tab("Reverse Text"):
        text_input2 = gr.Textbox(label="Enter text", lines=5)
        reverse_output = gr.Textbox(label="Reversed", lines=5)
        gr.Button("Reverse").click(reverse_text, text_input2, reverse_output)
    
    with gr.Tab("Count Vowels"):
        text_input3 = gr.Textbox(label="Enter text")
        vowel_output = gr.Number(label="Vowel Count")
        gr.Button("Count").click(count_vowels, text_input3, vowel_output)

if __name__ == "__main__":
    demo.launch(mcp_server=True)
