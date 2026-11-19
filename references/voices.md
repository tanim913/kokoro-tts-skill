# Kokoro voices

The first letter of a voice is its language code, and the cell picks the language from it. The second letter is f (female) or m (male).

The tested voices are **af_heart** (American, the clearest; the default) and **bm_george** (British). Both have narrated a whole novel with this skill.

This list is Kokoro-82M's set as of version 0.9.x (hexgrad/Kokoro-82M, VOICES.md). If a voice fails with "not found", check that page; the set changes between releases.

| Code | Language | Voices |
|---|---|---|
| a | American English | af_heart, af_alloy, af_aoede, af_bella, af_jessica, af_kore, af_nicole, af_nova, af_river, af_sarah, af_sky, am_adam, am_echo, am_eric, am_fenrir, am_liam, am_michael, am_onyx, am_puck, am_santa |
| b | British English | bf_alice, bf_emma, bf_isabella, bf_lily, bm_daniel, bm_fable, bm_george, bm_lewis |
| e | Spanish | ef_dora, em_alex, em_santa |
| f | French | ff_siwis |
| h | Hindi | hf_alpha, hf_beta, hm_omega, hm_psi |
| i | Italian | if_sara, im_nicola |
| j | Japanese | jf_alpha, jf_gongitsune, jf_nezumi, jf_tebukuro, jm_kumo |
| p | Brazilian Portuguese | pf_dora, pm_alex, pm_santa |
| z | Mandarin Chinese | zf_xiaobei, zf_xiaoni, zf_xiaoxiao, zf_xiaoyi, zm_yunjian, zm_yunxi, zm_yunxia, zm_yunyang |

Notes:

- The English voices are the strongest. Kokoro's own grades put af_heart and af_bella at the top; bf_emma and bm_george are the best British ones.
- Japanese (j) and Mandarin (z) need extra packages; the cell installs `misaki[ja]` or `misaki[zh]` when a job uses them. These two have not been tested in this skill.
- Text must be in the voice's language. An English voice reading Spanish text sounds wrong, and the reverse too.
- Bangla is not supported by Kokoro.

## Asking the user

When the caller hasn't named voices, ask with one multi-select question. Offer these four, and say that "Other" takes any voice id from the table above:

1. af_heart + bm_george (Recommended): both tested voices, two files per text.
2. af_heart only: American, the clearest.
3. bm_george only: British.
4. Audition first: one short sample in several voices, so the user can choose by ear.

For an audition, build one cell with a 2-sentence sample from the user's own text (or a neutral sentence if the text is private and they'd rather not), and the voices they're curious about, for example
`--inline "<sample>" --id audition --voices af_heart,af_bella,bf_emma,bm_george,am_michael --title none`.
A 6-voice audition takes about a minute after the runtime is up.
