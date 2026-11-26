# Skugga: Biological Motion Perception & Point-Light Displays

## 1. Overview

**Biological motion perception** is the remarkable human ability to instantly recognize living movement (human or animal) from minimal visual cues, such as isolated points of light located at key joints.

* **Project Name:** **Skugga** (Swedish for *"shadow"*, pronounced *SKOO-gah*—honoring Swedish psychologist Gunnar Johansson's landmark 1973 research).
* **The Core Effect:** When static, a cluster of 10–12 dots appears as a random scatter. Once in motion (often within < 200 ms), the dots immediately coalesce into a recognizable human form engaged in action (walking, running, dancing).

## 2. Key Insights & Brain Mechanisms

### Information Extracted

Beyond basic presence, the brain extracts subtle physical and social attributes purely from dynamic joint displacement:

* **Actions:** Walking, jumping, limping, throwing, climbing.
* **Biomechanical Traits:** Gender, body mass distribution, posture.
* **Affective States:** Emotions like happiness, anger, sadness, or anxiety.
* **Identity:** Individual "gait signatures" (recognizing oneself or familiar people).

### Neural Processing

* **Superior Temporal Sulcus (STS):** The core brain region integrating visual form and motion streams for biological perception.
* **Mirror Neuron System:** Activates motor regions as if the viewer were performing the action.
* **Inversion Effect:** Turning point-light displays upside down severely impairs recognition, demonstrating reliance on top-down, gravity-aligned internal models.

## 3. Open-Source Datasets & Formats

### Recommended Datasets

1. **CMU Graphics Lab Motion Capture Database** (`mocap.cs.cmu.edu`)
   * Extensive library of human movements in skeletal frame representations.
2. **BioMotionLab (Nikolaus Troje)**
   * Benchmark perceptual psychology datasets with parameterized demographic and emotional gait traits.
3. **Vanrie & Verfaillie Database**
   * Standardized 3D coordinate trajectories across primary action categories.

### Common File Formats

* **`.c3d`**: Binary files containing 3D coordinate time series for physical markers.
* **`.bvh`**: Text-based Biovision Hierarchy format storing joint hierarchies and rotational motion channels.
* **`.csv` / `.json`**: Flattened spatial coordinate arrays per frame $(x, y, z)$.

## 4. Python Implementation (`skugga_walker.py`)

The following minimal script demonstrates the core visual mechanic of **Skugga**, generating a synthetic 2D point-light walker using `numpy` and `matplotlib`:

```python
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

def skugga_walker_frame(t):
    phase = t * 2 * np.pi
    
    # Core joints
    head     = [0, 1.6]
    shoulder = [0, 1.3]
    hip      = [0, 0.8]
    
    # Upper extremities
    l_elbow = [-0.15 + 0.1 * np.sin(phase), 1.1]
    r_elbow = [0.15 - 0.1 * np.sin(phase), 1.1]
    l_wrist = [-0.2 + 0.2 * np.sin(phase), 0.85]
    r_wrist = [0.2 - 0.2 * np.sin(phase), 0.85]
    
    # Lower extremities
    l_knee  = [0.15 * np.cos(phase), 0.4]
    r_knee  = [-0.15 * np.cos(phase), 0.4]
    l_ankle = [0.25 * np.cos(phase), 0.05]
    r_ankle = [-0.25 * np.cos(phase), 0.05]
    
    return np.array([
        head, shoulder, hip, 
        l_elbow, r_elbow, l_wrist, r_wrist, 
        l_knee, r_knee, l_ankle, r_ankle
    ])

# Render setup
fig, ax = plt.subplots(figsize=(5, 5))
ax.set_facecolor('black')
ax.set_xlim(-1, 1)
ax.set_ylim(-0.2, 1.8)
ax.axis('off')

dots, = ax.plot([], [], 'wo', ms=8)

def update(frame):
    coords = skugga_walker_frame(frame / 20.0)
    dots.set_data(coords[:, 0], coords[:, 1])
    return dots,

ani = FuncAnimation(fig, update, frames=100, interval=50, blit=True)
plt.show()
```
