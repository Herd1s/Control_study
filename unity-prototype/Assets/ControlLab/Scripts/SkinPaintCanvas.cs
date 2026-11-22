using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    /// <summary>Owns the transparent drawing texture and 20 undo snapshots; never edits the photo layer.</summary>
    public sealed class SkinPaintCanvas : VisualElement, IDisposable
    {
        readonly Action changed;
        readonly List<Color32[]> undo = new List<Color32[]>();
        readonly Texture2D drawing;
        readonly Color32[] pixels;
        int pointer = -1;
        Vector2 previous;
        bool disposed;
        public Color BrushColor { get; set; } = Color.white;
        public float BrushDiameter { get; set; } = 16f;
        public bool Erasing { get; set; }
        public Texture2D DrawingTexture => drawing;
        public int UndoCount => undo.Count;
        public int DrawingPixelCount { get; private set; }
        internal Color32[] Pixels => pixels;

        public SkinPaintCanvas(Texture2D initialDrawing, Action onChanged)
        {
            drawing = initialDrawing ?? throw new ArgumentNullException(nameof(initialDrawing));
            pixels = drawing.GetPixels32();
            changed = onChanged;
            name = "studio-paint-canvas";
            AddToClassList("studio-canvas");
            focusable = true;
            CountPixels();
            RegisterCallback<PointerDownEvent>(OnDown);
            RegisterCallback<PointerMoveEvent>(OnMove);
            RegisterCallback<PointerUpEvent>(OnUp);
            RegisterCallback<PointerCaptureOutEvent>(_ => FinishStroke(false));
            RegisterCallback<PointerCancelEvent>(_ => FinishStroke());
        }

        public void SetDisplay(Texture2D composite, Color bodyColor)
        {
            style.backgroundImage = new StyleBackground(composite);
            style.backgroundColor = bodyColor;
        }

        void OnDown(PointerDownEvent e)
        {
            if (e.button != 0 || pointer >= 0) return;
            e.StopImmediatePropagation();
            Focus();
            PushUndo();
            pointer = e.pointerId;
            this.CapturePointer(pointer);
            previous = ToPixel(e.localPosition);
            Stamp(previous);
            Publish();
        }

        void OnMove(PointerMoveEvent e)
        {
            if (pointer != e.pointerId || !this.HasPointerCapture(pointer)) return;
            e.StopImmediatePropagation();
            Vector2 next = ToPixel(e.localPosition);
            float distance = Vector2.Distance(previous, next);
            int segments = Mathf.Max(1, Mathf.CeilToInt(distance / Mathf.Max(1f, BrushDiameter * .18f)));
            for (int i = 1; i <= segments; i++) Stamp(Vector2.Lerp(previous, next, (float)i / segments));
            previous = next;
            Publish();
        }

        void OnUp(PointerUpEvent e)
        {
            if (pointer != e.pointerId) return;
            e.StopImmediatePropagation();
            FinishStroke();
        }

        Vector2 ToPixel(Vector3 local)
        {
            Rect rect = contentRect;
            return new Vector2(
                Mathf.Clamp01((local.x - rect.x) / Mathf.Max(1, rect.width)) * (drawing.width - 1),
                (1f - Mathf.Clamp01((local.y - rect.y) / Mathf.Max(1, rect.height))) * (drawing.height - 1));
        }

        void Stamp(Vector2 point)
        {
            float radius = Mathf.Max(1f, BrushDiameter * .5f);
            int minX = Mathf.Max(0, Mathf.FloorToInt(point.x - radius - 1));
            int maxX = Mathf.Min(drawing.width - 1, Mathf.CeilToInt(point.x + radius + 1));
            int minY = Mathf.Max(0, Mathf.FloorToInt(point.y - radius - 1));
            int maxY = Mathf.Min(drawing.height - 1, Mathf.CeilToInt(point.y + radius + 1));
            Color32 ink = BrushColor;
            for (int y = minY; y <= maxY; y++)
            for (int x = minX; x <= maxX; x++)
            {
                float coverage = Mathf.Clamp01(radius + .5f - Vector2.Distance(new Vector2(x, y), point));
                if (coverage <= 0) continue;
                int index = y * drawing.width + x;
                Color32 original = pixels[index];
                if (Erasing)
                {
                    original.a = (byte)Mathf.RoundToInt(original.a * (1f - coverage));
                    pixels[index] = original;
                }
                else
                {
                    float alpha = coverage * ink.a / 255f;
                    float oldWeight = original.a / 255f * (1f - alpha);
                    float combined = alpha + oldWeight;
                    pixels[index] = new Color32(
                        (byte)Mathf.RoundToInt((ink.r * alpha + original.r * oldWeight) / combined),
                        (byte)Mathf.RoundToInt((ink.g * alpha + original.g * oldWeight) / combined),
                        (byte)Mathf.RoundToInt((ink.b * alpha + original.b * oldWeight) / combined),
                        (byte)Mathf.RoundToInt(combined * 255f));
                }
            }
        }

        void PushUndo()
        {
            if (undo.Count == 20) undo.RemoveAt(0);
            undo.Add((Color32[])pixels.Clone());
        }

        public void FinishStroke(bool releaseCapture = true)
        {
            if (pointer < 0) return;
            int previousPointer = pointer;
            pointer = -1;
            if (releaseCapture && this.HasPointerCapture(previousPointer)) this.ReleasePointer(previousPointer);
            CountPixels();
            changed?.Invoke();
        }

        public void Undo()
        {
            FinishStroke();
            if (undo.Count == 0) return;
            Array.Copy(undo[undo.Count - 1], pixels, pixels.Length);
            undo.RemoveAt(undo.Count - 1);
            CountPixels();
            Publish();
        }

        public void ClearDrawing()
        {
            FinishStroke();
            if (DrawingPixelCount == 0) return;
            PushUndo();
            Array.Clear(pixels, 0, pixels.Length);
            DrawingPixelCount = 0;
            Publish();
        }

        void CountPixels()
        {
            int count = 0;
            foreach (Color32 pixel in pixels) if (pixel.a != 0) count++;
            DrawingPixelCount = count;
        }

        void Publish()
        {
            drawing.SetPixels32(pixels);
            drawing.Apply(false, false);
            changed?.Invoke();
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            FinishStroke();
            undo.Clear();
            UnityEngine.Object.Destroy(drawing);
        }
    }
}
