import gradio as gr

def letter_counter(word: str, letter: str) -> int:
    """Count occurrences of a letter in text.

    Args:
        word: The input text
        letter: The letter to search for

    Returns:
        The count of the letter
    """
    return word.lower().count(letter.lower())

def reverse_text(text: str) -> str:
    """Reverse a string.

    Args:
        text: The input text

    Returns:
        The reversed text
    """
    return text[::-1]

# Create UI
with gr.Blocks() as demo:
    with gr.Tab("Letter Counter"):
        word_input = gr.Textbox(label="Enter text")
        letter_input = gr.Textbox(label="Enter letter")
        count_output = gr.Number(label="Count")
        gr.Button("Count").click(letter_counter, [word_input, letter_input], count_output)

    with gr.Tab("Text Reversal"):
        text_input = gr.Textbox(label="Enter text")
        reversed_output = gr.Textbox(label="Reversed")
        gr.Button("Reverse").click(reverse_text, [text_input], reversed_output)

if __name__ == "__main__":
    demo.launch(mcp_server=True)
