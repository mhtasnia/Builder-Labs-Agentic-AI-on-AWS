# Use AI Services with Amazon SageMaker

Self notes from the lab *Use AI Services with Amazon SageMaker*. In a SageMaker Jupyter notebook I called five AWS AI services from Python to build a small document-processing pipeline: read a PDF, judge its sentiment, translate it, turn it into speech, and turn the speech back into text. A DIY challenge at the end asks for a second Polly conversion with a different voice.

## Repository contents

```
.
├── Use_AI_Services_SageMaker_Lab_Notes.md   # this file
└── resources/
    ├── UseAI-Notebook.ipynb                 # the lab notebook
    └── ABC_Corporation.pdf                  # the sample document processed in the lab
```

- Notebook: [resources/UseAI-Notebook.ipynb](resources/UseAI-Notebook.ipynb)
- Sample document: [resources/ABC_Corporation.pdf](resources/ABC_Corporation.pdf)

## The business scenario

The sample PDF is a Q1 2025 client communication report from a fictional company, ABC Corporation. It describes a manual process that is too slow and too costly:

| Metric in the report | Value |
|---|---|
| Daily client communications | 10,000+ |
| Annual processing cost | $1.5 million |
| Error rate | 15% |
| Processing time | Up to 48 hours per document |
| Manual staff required | 20+ full-time employees |

It also lists two needs: clients in Asia Pacific want immediate translation, and European clients want real-time sentiment analysis of customer feedback. Each AI service in the notebook answers part of this problem.

## Technologies used

| Service | What it does | API call used | Role in this lab |
|---|---|---|---|
| **Amazon SageMaker** | Managed machine learning environment | Jupyter notebook (Python 3.12) | Where the code runs |
| **Amazon S3** | Object storage | `s3.Object(...).put(...)` | Stores the PDF and the generated audio |
| **Amazon Textract** | Reads text from documents | `detect_document_text` | Extracts lines of text from the PDF |
| **Amazon Comprehend** | Natural language understanding | `detect_sentiment` | Scores the emotional tone of the text |
| **Amazon Translate** | Machine translation | `translate_text` | Converts the text to French |
| **Amazon Polly** | Text to speech | `synthesize_speech` | Creates an MP3 with the voice Joanna |
| **Amazon Transcribe** | Speech to text | `start_transcription_job`, `get_transcription_job` | Turns the MP3 back into text |
| **boto3** | The AWS SDK for Python | `boto3.client(...)`, `boto3.resource(...)` | Calls all of the above |

Libraries used in the notebook: `boto3`, `json`, `urllib.request`, `time` and `IPython.display.Audio` (the in-notebook audio player).

## The pipeline

```
ABC_Corporation.pdf (S3)
     │  Textract
     ▼
extracted_text ──> Comprehend ──> sentiment (NEUTRAL)
     │
     ├──> Translate ──> French text
     │
     └──> Polly (Joanna) ──> lab-output.mp3 (S3: audio-output/)
                                   │  Transcribe
                                   ▼
                            transcript text
```

## What I did, step by step

### Setup

One cell creates the clients. Textract, Comprehend, Translate, Transcribe and Polly use `boto3.client(...)`, and S3 uses `boto3.resource('s3')`. I set `bucket_name` to the lab's S3 bucket (left empty in the saved notebook) and `document_name = "ABC_Corporation.pdf"`.

### Step 1: Extract text with Textract

```python
def extract_text_from_pdf(bucket_name, document_name):
    response = textract.detect_document_text(
        Document={'S3Object': {'Bucket': bucket_name, 'Name': document_name}}
    )
    text = [item['Text'] for item in response['Blocks'] if item['BlockType'] == 'LINE']
    return '\n'.join(text)
```

- Textract returns a list of **blocks** (pages, lines, words). The function keeps only `LINE` blocks and joins them with line breaks.
- The result was the full report text: the executive summary, the process statistics, the client feedback sample and the urgent action list.
- `detect_document_text` is the synchronous API, which suits short documents. Long multi-page PDFs need the asynchronous `start_document_text_detection`.

### Step 2: Sentiment with Comprehend

```python
def analyze_sentiment(text):
    return comprehend.detect_sentiment(Text=text[:5000], LanguageCode='en')
```

Result:

| Sentiment | Score |
|---|---|
| **NEUTRAL** (overall) | 97.9% |
| Positive | 1.4% |
| Negative | 0.6% |
| Mixed | 0.06% |

**Observation:** the report includes a client who is "extremely frustrated" and calls the error rate "unacceptable", yet the overall result is neutral. Most of the text is a formal report with statistics, so the whole-document score is dominated by neutral wording. To measure customer feelings, the sentiment should be run on the feedback paragraph alone, or sentence by sentence. The notebook also notes the size limit: the API accepts about 5,000 characters (the real limit is measured in bytes), so the input is cut with `text[:5000]`.

### Step 3: Translate with Translate

```python
def translate_text(text, target_lang='es'):
    response = translate.translate_text(
        Text=text[:5000], SourceLanguageCode='auto', TargetLanguageCode=target_lang)
    return response['TranslatedText']

translated_text = translate_text(extracted_text, 'fr')
```

- `SourceLanguageCode='auto'` lets the service detect the language, and I asked for French (`fr`).
- The French output read well overall (for example "Rapport d'analyse des communications avec les clients").

**Observation:** a few sentences came out garbled, with repeated words ("Ce / Ce document") and a stray fragment ("exiger des exigences de manière efficace"). The cause is that Textract returns the text line by line, so a sentence that wraps across two lines is translated as two separate pieces. Joining lines into paragraphs before translating should fix this.

### Step 4: Text to speech with Polly

```python
def text_to_speech(text, filename):
    response = polly.synthesize_speech(Text=text[:3000], OutputFormat='mp3', VoiceId='Joanna')
    audio_stream = response['AudioStream'].read()
    s3.Object(bucket_name, f"audio-output/{filename}.mp3").put(Body=audio_stream)
    print(f"Audio saved: s3://{bucket_name}/audio-output/{filename}.mp3")
    return Audio(data=audio_stream, autoplay=False)
```

- The text is limited to 3,000 characters per request.
- The MP3 is saved to S3 as `audio-output/lab-output.mp3`, and `Audio(...)` shows a player in the notebook so I can listen to it.

### Step 5: Speech to text with Transcribe

```python
transcribe.start_transcription_job(
    TranscriptionJobName="lab-transcription-job",
    Media={'MediaFileUri': f"s3://{bucket_name}/audio-output/{audio_file}"},
    MediaFormat='mp3',
    LanguageCode='en-US',
)
# poll get_transcription_job every 5 seconds until COMPLETED or FAILED
# then download the JSON from TranscriptFileUri and read results.transcripts[0].transcript
```

- Transcribe is asynchronous. The notebook polls until the job finishes, then downloads the result JSON through `urllib` and reads the transcript text.
- Round trip result: the transcript matched the original text closely.

**Observations:**
- It made a small mistake: "high error rates" was heard as "higher rates". The punctuation also differs, with run-together phrases such as "Q1 2025 executive summary" and odd breaks such as "Processing. Time up to 48 hours".
- The job name `lab-transcription-job` is hard-coded. Transcribe job names must be unique, so running the cell a second time would fail unless the old job is deleted or the name changes (for example by adding a timestamp).

## DIY challenge

**The task:** the notebook gives a template function, `diy_polly_conversion`, that is meant to run another Polly conversion with a different voice (`Matthew`) and save it under a `diy-output/` folder. Two spots are marked `TODO: Modify this function`: the `OutputFormat` and the `Body` that is uploaded to S3. The Step 4 cell is the reference.

**The bug in the template:** the upload used a quoted string:

```python
s3.Object(bucket_name, f"diy-output/{filename}.mp3").put(Body="audio_stream2")
```

`"audio_stream2"` is just text. S3 would receive those 13 characters as the "MP3 file", not the audio. The notebook player would still play, because it uses the `audio_stream` variable directly, so the problem is easy to miss.

**The fix (based on the template and the Step 4 pattern):**

```python
def diy_polly_conversion(text, filename):
    response = polly.synthesize_speech(
        Text=text[:3000],
        OutputFormat='mp3',      # a real audio format (mp3, ogg_vorbis or pcm)
        VoiceId='Matthew'        # a different voice from Step 4 (Joanna)
    )
    audio_stream = response['AudioStream'].read()

    s3.Object(bucket_name, f"diy-output/{filename}.mp3").put(
        Body=audio_stream        # the variable holding the audio bytes, not a string
    )
    print(f"Audio saved: s3://{bucket_name}/diy-output/{filename}.mp3")
    return Audio(data=audio_stream, autoplay=False)

audio_player = diy_polly_conversion(extracted_text[:3000], "diy-result")
display(audio_player)
```

**How to check it worked:** the audio player plays the Matthew voice, and `diy-output/diy-result.mp3` in S3 is a real audio file with a size of tens of kilobytes (not 13 bytes).

> I wrote this section from the notebook's template, since I can't see what you actually changed. Edit it to match your solution (for example a different voice, text length or output name).

## Lessons learned

- Each AI service takes one input type and returns one output type, so they chain well: file to text, text to sentiment or translation, text to audio, audio to text.
- Textract returns structure (blocks), and the code decides what to keep. Here it kept `LINE` blocks only.
- Slicing text (`[:5000]`, `[:3000]`) is a quick way to stay within API limits, but it silently drops everything after the limit.
- Sentiment depends on what text goes in. A whole-document score can hide strong feelings in one paragraph.
- Line breaks from OCR hurt translation, so clean up the text between steps.
- A round trip (text to speech to text) is a quick quality check, and it showed a small transcription error.
- Asynchronous services (Transcribe, and Textract for long documents) need polling and unique job names.

## How this maps to the business problem

| Need in the report | Service that helps |
|---|---|
| Documents arrive as PDFs and are read by hand | Textract |
| Real-time sentiment on customer feedback (Europe) | Comprehend |
| Immediate translation (Asia Pacific) | Translate |
| Accessibility, voice delivery, call-style output | Polly |
| Turning calls and voice messages into searchable text | Transcribe |

## Production considerations

- **Limits and long documents.** Use the asynchronous Textract API for multi-page PDFs, split long text into chunks for Comprehend and Translate, and don't silently cut text.
- **Detect the language** instead of hard-coding `en` for sentiment. Comprehend can identify the dominant language, and Translate's `auto` option also relies on language detection.
- **Quality and review.** Machine translation and transcription make mistakes (like "higher rates"). For legal or customer-facing content, add a human check or custom vocabularies and terminology.
- **Cost.** All five services are billed by usage (pages, characters or seconds). Processing 10,000+ documents a day needs a cost estimate and batching.
- **Privacy.** Documents can contain personal data. Use encryption for the S3 bucket, least-privilege IAM roles for the notebook, and consider Comprehend's PII detection before storing or sharing results.
- **Clean up.** Delete finished Transcribe jobs and generated audio you no longer need, and give jobs unique names.
- **Error handling.** The notebook doesn't handle API errors, retries or throttling. A production pipeline would.

