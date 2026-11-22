using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    /// <summary>A presentation layer for the first, deliberately ungated lesson.</summary>
    [DisallowMultipleComponent]
    public sealed partial class LessonOneExperience : MonoBehaviour
    {
        public PendulumModel Model { get; private set; }
        public Camera PresentationCamera => sceneCamera;
        public UIDocument Document => document;
        public bool ExplanationOpen => explanationOpen;
        public int ActiveConcept => activeConcept;
        public Vector3 CartScreenPosition => sceneCamera == null ? Vector3.zero :
            sceneCamera.WorldToScreenPoint(cart.TransformPoint(new Vector3(0, .35f, -.2f)));

        const float PoleLength = 1f;
        const float PivotHeight = .48f;
        readonly Plane dragPlane = new Plane(Vector3.forward, Vector3.zero);
        readonly List<UnityEngine.Object> ownedAssets = new List<UnityEngine.Object>();
        Transform sceneRoot, cart, pole, leftWheel, rightWheel, gravityMarker;
        Camera sceneCamera;
        Light keyLight;
        Material cartMaterial, haloMaterial;
        LineRenderer leftCue, rightCue, momentumVector, gravityVector;
        UIDocument document;
        PanelSettings panelSettings;
        VisualElement overlay, hero, explanation, footer;
        Label headline, guidance, explanationText;
        Button resetButton, nudgeButton, explainButton;
        readonly Button[] conceptButtons = new Button[3];
        readonly string[] conceptDescriptions =
        {
            "蓝箭头表示小车动量方向（p=mv），合外力冲量会改变动量。\n从竖直静止开始向右加速，杆会因惯性先向左倾。",
            "橙色箭头是杆的重力，杆偏斜时会对支点产生力矩。\n杆怎么转，还取决于小车的加速度。",
            "杆刚向右倾时，适当向右加速小车，可能接住它。\n还要看杆的转速，及时减速或反向。"
        };
        double accumulator;
        float appearanceTime, hoverAmount, cueAmount = 1f;
        double pointerOffset;
        bool pointerDragging, hasTried, wasFallen, explanationOpen;
        int lastWidth, lastHeight, activeConcept;

        void Awake()
        {
            Model = new PendulumModel();
            QualitySettings.vSyncCount = 1;
            Application.targetFrameRate = 60;
            BuildScene();
            BuildInterface();
            progress = LearningProgressStore.Load();
            preferences = AppPreferencesStore.Load(progress);
            InitializeWelcome();
            InitializeSettings();
            RestoreLearningProgress();
            RefreshPose();
            UpdateResponsiveLayout();
        }

        void BuildScene()
        {
            sceneRoot = new GameObject("Lesson one presentation").transform;
            sceneRoot.SetParent(transform, false);
            var cameraObject = new GameObject("Lesson camera", typeof(Camera));
            cameraObject.transform.SetParent(sceneRoot, false);
            sceneCamera = cameraObject.GetComponent<Camera>();
            sceneCamera.tag = "MainCamera";
            sceneCamera.orthographic = true;
            sceneCamera.orthographicSize = 2.3f;
            sceneCamera.clearFlags = CameraClearFlags.SolidColor;
            sceneCamera.backgroundColor = Hex("F5F6F8");
            sceneCamera.nearClipPlane = .05f;
            sceneCamera.farClipPlane = 60f;
            sceneCamera.allowHDR = false;
            sceneCamera.allowMSAA = true;
            cameraObject.transform.position = new Vector3(0, 2.5f, -9f);
            cameraObject.transform.LookAt(new Vector3(0, .92f, 0));
            cameraObject.AddComponent<AudioListener>();

            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(.73f, .76f, .82f);
            RenderSettings.fog = false;
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = ShadowResolution.High;
            QualitySettings.shadowDistance = 22;
            QualitySettings.antiAliasing = 4;
            keyLight = new GameObject("Soft key light", typeof(Light)).GetComponent<Light>();
            keyLight.transform.SetParent(sceneRoot, false);
            keyLight.type = LightType.Directional;
            keyLight.color = new Color(1f, .98f, .95f);
            keyLight.intensity = 1.05f;
            keyLight.shadows = LightShadows.Soft;
            keyLight.shadowStrength = .24f;
            keyLight.shadowBias = .03f;
            keyLight.shadowNormalBias = .12f;
            keyLight.transform.rotation = Quaternion.Euler(44, -26, 0);
            var fill = new GameObject("Blue-white fill", typeof(Light)).GetComponent<Light>();
            fill.transform.SetParent(sceneRoot, false);
            fill.type = LightType.Directional;
            fill.color = new Color(.83f, .9f, 1f);
            fill.intensity = .32f;
            fill.transform.rotation = Quaternion.Euler(28, 135, 0);

            var groundMaterial = Surface("Porcelain floor", Hex("F5F6F8"), 0f, .12f);
            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Quiet studio floor";
            ground.transform.SetParent(sceneRoot, false);
            ground.transform.localScale = new Vector3(8, 1, 8);
            ground.transform.position = new Vector3(0, -.02f, 0);
            ground.GetComponent<Renderer>().sharedMaterial = groundMaterial;
            RemoveCollider(ground);

            var rail = Surface("Rail ceramic", Hex("E6E9EE"), .12f, .4f);
            RoundedBox("Floating track", sceneRoot, new Vector3(5.65f, .085f, .65f), .04f,
                new Vector3(0, .075f, .04f), rail);
            var railTop = Surface("Rail inset", Hex("D1D8E2"), .38f, .55f);
            RoundedBox("Track line", sceneRoot, new Vector3(5.36f, .022f, .035f), .01f,
                new Vector3(0, .128f, -.18f), railTop);
            var center = Surface("Origin inlay", Hex("A5B6CA"), .3f, .35f);
            RoundedBox("Center inlay", sceneRoot, new Vector3(.025f, .007f, .2f), .003f,
                new Vector3(0, .121f, .12f), center);

            cart = new GameObject("Draggable cart").transform;
            cart.SetParent(sceneRoot, false);
            cartMaterial = Surface("Satin blue cart", Hex("0878E8"), .12f, .42f);
            RoundedBox("Rounded body", cart, new Vector3(.74f, .3f, .49f), .085f,
                new Vector3(0, .33f, 0), cartMaterial);
            upperMaterial = Surface("Cart upper inset", Hex("7FB8F3"), .18f, .5f);
            RoundedBox("Recessed top", cart, new Vector3(.55f, .025f, .32f), .012f,
                new Vector3(0, .479f, 0), upperMaterial);
            var dark = Surface("Rubber wheels", Hex("293441"), .08f, .22f);
            var rim = Surface("Brushed wheel hubs", Hex("D4DEE8"), .65f, .5f);
            leftWheel = Wheel("Left wheel", -.235f, cart, dark, rim);
            rightWheel = Wheel("Right wheel", .235f, cart, dark, rim);
            var collider = cart.gameObject.AddComponent<BoxCollider>();
            collider.center = new Vector3(0, .32f, 0);
            collider.size = new Vector3(.94f, .52f, .72f);

            pole = new GameObject("Pendulum pivot").transform;
            pole.SetParent(cart, false);
            pole.localPosition = new Vector3(0, PivotHeight, 0);
            var shaft = Surface("Pearl aluminium", Hex("B7C4D3"), .62f, .52f);
            var cap = Surface("Pivot porcelain", Hex("F9FCFF"), .22f, .5f);
            var stem = Cylinder("Slender rod", pole, new Vector3(0, PoleLength * .5f, 0),
                new Vector3(.038f, PoleLength * .5f, .038f), shaft);
            stem.transform.localRotation = Quaternion.identity;
            Sphere("Pole tip", pole, new Vector3(0, PoleLength, 0), .084f, shaft);
            Sphere("Tip glint", pole, new Vector3(0, PoleLength, -.041f), .032f, cap);
            var pivotHub = Cylinder("Pivot bearing", cart, new Vector3(0, PivotHeight, -.02f),
                new Vector3(.12f, .042f, .12f), cap);
            pivotHub.transform.localRotation = Quaternion.Euler(90, 0, 0);
            Sphere("Pivot center", cart, new Vector3(0, PivotHeight, -.068f), .042f, cartMaterial);

            leftCue = Cue("Left drag cue", -1);
            rightCue = Cue("Right drag cue", 1);
            CreateConceptVisuals();
            CreateContactShadow();
        }

        Material Surface(string name, Color color, float metallic, float gloss)
        {
            var material = new Material(Shader.Find("Standard")) { name = name, color = color };
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Glossiness", gloss);
            ownedAssets.Add(material);
            return material;
        }

        GameObject RoundedBox(string name, Transform parent, Vector3 size, float radius, Vector3 position, Material material)
        {
            var item = new GameObject(name, typeof(MeshFilter), typeof(MeshRenderer));
            item.transform.SetParent(parent, false);
            item.transform.localPosition = position;
            var mesh = RoundedBoxMesh(size, radius);
            ownedAssets.Add(mesh);
            item.GetComponent<MeshFilter>().sharedMesh = mesh;
            item.GetComponent<MeshRenderer>().sharedMaterial = material;
            return item;
        }

        static Mesh RoundedBoxMesh(Vector3 size, float radius)
        {
            const int segments = 16;
            var vertices = new List<Vector3>();
            var normals = new List<Vector3>();
            var indices = new List<int>();
            Vector3 half = size * .5f;
            radius = Mathf.Min(radius, Mathf.Min(half.x, Mathf.Min(half.y, half.z)));
            Vector3 core = half - Vector3.one * radius;
            Vector3[] normalAxes = {Vector3.right, Vector3.left, Vector3.up, Vector3.down, Vector3.forward, Vector3.back};
            foreach (Vector3 normal in normalAxes)
            {
                Vector3 u = Mathf.Abs(normal.y) > .5f ? Vector3.right : Vector3.up;
                Vector3 v = Vector3.Cross(normal, u);
                int first = vertices.Count;
                for (int y = 0; y <= segments; y++)
                for (int x = 0; x <= segments; x++)
                {
                    Vector3 unit = normal + u * (2f * x / segments - 1f) + v * (2f * y / segments - 1f);
                    Vector3 outer = Vector3.Scale(unit, half);
                    Vector3 nearest = new Vector3(Mathf.Clamp(outer.x, -core.x, core.x),
                        Mathf.Clamp(outer.y, -core.y, core.y), Mathf.Clamp(outer.z, -core.z, core.z));
                    Vector3 vertexNormal = (outer - nearest).normalized;
                    vertices.Add(nearest + vertexNormal * radius);
                    normals.Add(vertexNormal);
                }
                for (int y = 0; y < segments; y++)
                for (int x = 0; x < segments; x++)
                {
                    int a = first + y * (segments + 1) + x;
                    int b = a + 1, c = a + segments + 1, d = c + 1;
                    indices.Add(a); indices.Add(b); indices.Add(c);
                    indices.Add(b); indices.Add(d); indices.Add(c);
                }
            }
            var result = new Mesh { name = "Rounded box" };
            result.SetVertices(vertices);
            result.SetNormals(normals);
            result.SetTriangles(indices, 0);
            result.RecalculateBounds();
            return result;
        }

        Transform Wheel(string name, float x, Transform parent, Material rubber, Material rim)
        {
            var wheel = new GameObject(name).transform;
            wheel.SetParent(parent, false);
            wheel.localPosition = new Vector3(x, .22f, -.235f);
            var tire = Cylinder("Rubber", wheel, Vector3.zero, new Vector3(.19f, .043f, .19f), rubber);
            tire.transform.localRotation = Quaternion.Euler(90, 0, 0);
            var hub = Cylinder("Hub", wheel, new Vector3(0, 0, -.045f), new Vector3(.105f, .006f, .105f), rim);
            hub.transform.localRotation = Quaternion.Euler(90, 0, 0);
            return wheel;
        }

        GameObject Cylinder(string name, Transform parent, Vector3 position, Vector3 scale, Material material)
        {
            var item = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            item.name = name;
            item.transform.SetParent(parent, false);
            item.transform.localPosition = position;
            item.transform.localScale = scale;
            item.GetComponent<Renderer>().sharedMaterial = material;
            RemoveCollider(item);
            return item;
        }

        void Sphere(string name, Transform parent, Vector3 position, float size, Material material)
        {
            var item = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            item.name = name;
            item.transform.SetParent(parent, false);
            item.transform.localPosition = position;
            item.transform.localScale = Vector3.one * size;
            item.GetComponent<Renderer>().sharedMaterial = material;
            RemoveCollider(item);
        }

        void RemoveCollider(GameObject item)
        {
            var collider = item.GetComponent<Collider>();
            if (collider != null) { collider.enabled = false; Destroy(collider); }
        }

        LineRenderer Cue(string name, int direction)
        {
            var item = new GameObject(name, typeof(LineRenderer));
            item.transform.SetParent(cart, false);
            var line = item.GetComponent<LineRenderer>();
            line.useWorldSpace = false;
            var material = new Material(Shader.Find("Sprites/Default"));
            ownedAssets.Add(material);
            line.sharedMaterial = material;
            line.startWidth = line.endWidth = .012f;
            line.numCapVertices = 6;
            line.numCornerVertices = 6;
            line.positionCount = 5;
            float start = direction * .58f, end = direction * .88f;
            line.SetPositions(new[] { new Vector3(start, .32f, 0), new Vector3(end, .32f, 0),
                new Vector3(end - direction * .07f, .37f, 0), new Vector3(end, .32f, 0),
                new Vector3(end - direction * .07f, .27f, 0) });
            return line;
        }

        void CreateConceptVisuals()
        {
            momentumVector = ConceptArrow("Momentum vector", Hex("0066CC"));
            gravityVector = ConceptArrow("Gravity vector", Hex("D77A2F"));
            var marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            marker.name = "Pole centre of mass";
            gravityMarker = marker.transform;
            gravityMarker.SetParent(sceneRoot, false);
            gravityMarker.localScale = Vector3.one * .075f;
            marker.GetComponent<Renderer>().sharedMaterial = Surface("Gravity marker", Hex("D77A2F"), 0f, .3f);
            RemoveCollider(marker);
            marker.SetActive(false);
        }

        LineRenderer ConceptArrow(string name, Color color)
        {
            var item = new GameObject(name, typeof(LineRenderer));
            item.transform.SetParent(sceneRoot, false);
            var line = item.GetComponent<LineRenderer>();
            line.useWorldSpace = true;
            var material = new Material(Shader.Find("Sprites/Default"));
            ownedAssets.Add(material);
            line.sharedMaterial = material;
            line.startColor = line.endColor = color;
            line.startWidth = line.endWidth = .022f;
            line.numCapVertices = 6;
            line.numCornerVertices = 6;
            line.positionCount = 5;
            line.shadowCastingMode = ShadowCastingMode.Off;
            line.receiveShadows = false;
            line.enabled = false;
            return line;
        }

        static void SetArrow(LineRenderer line, Vector3 start, Vector3 direction, float length)
        {
            Vector3 end = start + direction * length;
            Vector3 wing = Vector3.Cross(Vector3.forward, direction) * .055f;
            line.SetPosition(0, start);
            line.SetPosition(1, end);
            line.SetPosition(2, end - direction * .09f + wing);
            line.SetPosition(3, end);
            line.SetPosition(4, end - direction * .09f - wing);
        }

        void RefreshConceptVisuals()
        {
            if (stage != ExperienceStage.Lesson)
            {
                leftCue.enabled = rightCue.enabled = momentumVector.enabled = gravityVector.enabled = false;
                gravityMarker.gameObject.SetActive(false);
                return;
            }
            // Drag cues must never be mistaken for momentum arrows at rest.
            leftCue.enabled = rightCue.enabled = !explanationOpen;
            bool momentumVisible = explanationOpen && activeConcept == 0 && Math.Abs(Model.V) > .025;
            momentumVector.enabled = momentumVisible;
            if (momentumVisible)
            {
                float direction = Model.V > 0 ? 1f : -1f;
                Vector3 start = cart.position + new Vector3(0, .6f, -.36f);
                // A fixed-length direction cue, not a quantitative momentum scale.
                SetArrow(momentumVector, start, Vector3.right * direction, .58f);
            }
            bool gravityVisible = explanationOpen && activeConcept == 1;
            gravityVector.enabled = gravityVisible;
            gravityMarker.gameObject.SetActive(gravityVisible);
            if (gravityVisible)
            {
                Vector3 centre = pole.TransformPoint(new Vector3(0, PoleLength * .5f, 0));
                gravityMarker.position = centre + Vector3.back * .045f;
                // Gravity stays vertically downward in world space as the pole rotates.
                SetArrow(gravityVector, centre + Vector3.back * .055f, Vector3.down, .38f);
            }
        }

        void CreateContactShadow()
        {
            var texture = new Texture2D(64, 64, TextureFormat.RGBA32, false);
            texture.name = "Soft contact";
            texture.wrapMode = TextureWrapMode.Clamp;
            for (int y = 0; y < 64; y++)
            for (int x = 0; x < 64; x++)
            {
                float radius = new Vector2((x - 31.5f) / 31.5f, (y - 31.5f) / 31.5f).magnitude;
                float alpha = Mathf.Pow(Mathf.Clamp01(1f - radius), 2) * .2f;
                texture.SetPixel(x, y, new Color(.14f, .22f, .35f, alpha));
            }
            texture.Apply(false, true);
            ownedAssets.Add(texture);
            // The Resources reference retains this runtime-only shader in a standalone build.
            haloMaterial = new Material(Resources.Load<Shader>("SoftContact"));
            haloMaterial.mainTexture = texture;
            ownedAssets.Add(haloMaterial);
            var shadow = GameObject.CreatePrimitive(PrimitiveType.Quad);
            shadow.name = "Contact shadow";
            shadow.transform.SetParent(cart, false);
            shadow.transform.localPosition = new Vector3(0, .133f, .03f);
            shadow.transform.localRotation = Quaternion.Euler(90, 0, 0);
            shadow.transform.localScale = new Vector3(1.28f, .85f, 1);
            shadow.GetComponent<Renderer>().sharedMaterial = haloMaterial;
            shadow.GetComponent<Renderer>().shadowCastingMode = ShadowCastingMode.Off;
            shadow.GetComponent<Renderer>().receiveShadows = false;
            RemoveCollider(shadow);
        }

        void BuildInterface()
        {
            // A persisted asset retains Unity's ICU/text-rendering resources in the Player.
            // Creating a fresh PanelSettings only at runtime loses those internal references.
            var panelTemplate = Resources.Load<PanelSettings>("LessonOnePanel");
            if (panelTemplate == null)
                throw new InvalidOperationException("LessonOnePanel is missing. Run ControlLab/Open first lesson before building.");
            panelSettings = Instantiate(panelTemplate);
            panelSettings.name = "ControlLab runtime panel";
            panelSettings.scaleMode = PanelScaleMode.ConstantPixelSize;
            panelSettings.sortingOrder = 10;
            panelSettings.themeStyleSheet = Resources.Load<ThemeStyleSheet>("LessonOneTheme");
            ownedAssets.Add(panelSettings);
            document = gameObject.AddComponent<UIDocument>();
            document.panelSettings = panelSettings;
            overlay = document.rootVisualElement;
            overlay.name = "lesson-one";
            overlay.pickingMode = PickingMode.Ignore;
            var styles = Resources.Load<StyleSheet>("LessonOne");
            if (styles != null) overlay.styleSheets.Add(styles);
            var font = Font.CreateDynamicFontFromOSFont(new[] {"Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Arial"}, 32);
            // ATG resolves OS font faces by this original family name. Do not rename it.
            ownedAssets.Add(font);
            overlay.style.unityFontDefinition = FontDefinition.FromFont(font);

            var top = Element("topbar", overlay);
            var brand = Element("brand", top);
            var logo = new Label("C") { name = "brand-mark", pickingMode = PickingMode.Ignore };
            brand.Add(logo);
            brand.Add(new Label("ControlLab") { name = "brand-name", pickingMode = PickingMode.Ignore });
            top.Add(new Label("第一课 · 自由探索") { name = "lesson-caption", pickingMode = PickingMode.Ignore });

            hero = Element("hero", overlay);
            headline = new Label("抓住小车，\n试着接住杆。") { name = "headline", pickingMode = PickingMode.Ignore };
            hero.Add(headline);
            guidance = new Label("不急，先感受它的变化。") { name = "guidance", pickingMode = PickingMode.Ignore };
            hero.Add(guidance);

            explanation = Element("explanation", overlay);
            var concepts = Element("concepts", explanation);
            string[] conceptNames = { "concept-momentum", "concept-gravity", "concept-control" };
            string[] conceptTitles = { "动量与惯性", "重力与力矩", "怎样接住" };
            for (int i = 0; i < conceptButtons.Length; i++)
            {
                int index = i;
                var button = new Button(() => SelectConcept(index))
                    { name = conceptNames[i], text = conceptTitles[i] };
                button.AddToClassList("concept");
                conceptButtons[i] = button;
                concepts.Add(button);
            }
            explanationText = new Label { name = "explanation-text", pickingMode = PickingMode.Ignore };
            explanation.Add(explanationText);
            SelectConcept(0);
            explanation.style.display = DisplayStyle.None;
            footer = Element("footer", overlay);
            resetButton = new Button(ResetExperiment) { text = "再试一次", name = "reset-button" };
            resetButton.AddToClassList("pill"); resetButton.AddToClassList("primary");
            footer.Add(resetButton);
            nudgeButton = new Button(Nudge) { text = "轻推一下", name = "nudge-button" };
            nudgeButton.AddToClassList("pill"); nudgeButton.AddToClassList("secondary");
            footer.Add(nudgeButton);
            explainButton = new Button(ToggleExplanation) { text = "为什么会倒？", name = "explain-button" };
            explainButton.AddToClassList("pill"); explainButton.AddToClassList("quiet");
            footer.Add(explainButton);
            overlay.RegisterCallback<GeometryChangedEvent>(_ => UpdateResponsiveLayout());
        }

        static VisualElement Element(string name, VisualElement parent)
        {
            var item = new VisualElement { name = name, pickingMode = PickingMode.Ignore };
            parent.Add(item);
            return item;
        }

        void ToggleExplanation()
        {
            explanationOpen = !explanationOpen;
            explanation.style.display = explanationOpen ? DisplayStyle.Flex : DisplayStyle.None;
            hero.style.display = explanationOpen ? DisplayStyle.None : DisplayStyle.Flex;
            explainButton.text = explanationOpen ? "收起说明" : "为什么会倒？";
            explainButton.EnableInClassList("selected", explanationOpen);
            RefreshConceptVisuals();
            SaveLearningProgress();
        }

        public void SelectConcept(int index)
        {
            if (index < 0 || index >= conceptButtons.Length) throw new ArgumentOutOfRangeException(nameof(index));
            activeConcept = index;
            explanationText.text = conceptDescriptions[index];
            for (int i = 0; i < conceptButtons.Length; i++)
                conceptButtons[i].EnableInClassList("selected", i == index);
            RefreshConceptVisuals();
            SaveLearningProgress();
        }

        void UpdateResponsiveLayout()
        {
            if (overlay == null || sceneCamera == null) return;
            bool compact = Screen.width < 900;
            overlay.EnableInClassList("compact", compact);
            explanation.style.maxWidth = Mathf.Max(1, Screen.width - 48);
            sceneCamera.orthographicSize = Mathf.Max(2.3f, 3f / Mathf.Max(.7f, (float)Screen.width / Mathf.Max(1, Screen.height)));
            lastWidth = Screen.width;
            lastHeight = Screen.height;
        }

        void Update()
        {
            if (Model == null) return;
            if (Screen.width != lastWidth || Screen.height != lastHeight)
            {
                EndDrag();
                UpdateResponsiveLayout();
            }
            TickSettings();
            if (settingsOpen)
            {
                if (Input.GetKeyDown(KeyCode.Escape)) CloseSettings();
                return;
            }
            TickWelcome();
            if (stage != ExperienceStage.Lesson) return;
            ReadPointer();
            if (Model.IsRunning)
            {
                accumulator += Mathf.Min(Time.unscaledDeltaTime, .1f);
                while (accumulator >= PendulumModel.Dt)
                {
                    Model.Tick();
                    accumulator -= PendulumModel.Dt;
                    if (!Model.IsRunning) { accumulator = 0; break; }
                }
            }
            else accumulator = 0;
            RefreshPose();
            RefreshInterface();
            if (Input.GetKeyDown(KeyCode.Escape)) EndDrag();
        }

        void ReadPointer()
        {
            if (ignorePointerUntilReleased)
            {
                if (!Input.GetMouseButton(0)) ignorePointerUntilReleased = false;
                return;
            }
            bool overUI = PointerOverButton();
            bool overCart = !overUI && RayHitsCart();
            float desiredHover = pointerDragging || overCart ? 1 : 0;
            hoverAmount = Mathf.MoveTowards(hoverAmount, desiredHover, Time.unscaledDeltaTime * 7);
            if (Input.GetMouseButtonDown(0) && overCart && PointerOnPlane(out Vector3 point))
            {
                BeginDrag();
                pointerOffset = point.x - Model.X;
                pointerDragging = true;
            }
            if (pointerDragging && Input.GetMouseButton(0) && PointerOnPlane(out Vector3 dragPoint))
                DragTo(dragPoint.x - pointerOffset);
            if (pointerDragging && (!Input.GetMouseButton(0) || Model.HasFallen)) EndDrag();
        }

        bool RayHitsCart()
        {
            if (sceneCamera == null || cart == null) return false;
            if (!Physics.Raycast(sceneCamera.ScreenPointToRay(Input.mousePosition), out RaycastHit hit, 30f)) return false;
            return hit.transform == cart || hit.transform.IsChildOf(cart);
        }

        bool PointerOnPlane(out Vector3 point)
        {
            Ray ray = sceneCamera.ScreenPointToRay(Input.mousePosition);
            if (dragPlane.Raycast(ray, out float distance)) { point = ray.GetPoint(distance); return true; }
            point = default;
            return false;
        }

        bool PointerOverButton()
        {
            if (overlay?.panel == null) return false;
            Vector2 point = Input.mousePosition;
            point.y = Screen.height - point.y;
            var picked = overlay.panel.Pick(RuntimePanelUtils.ScreenToPanel(overlay.panel, point));
            while (picked != null)
            {
                if (picked is Button) return true;
                picked = picked.parent;
            }
            return false;
        }

        public void BeginDrag()
        {
            Model.BeginDrag();
            hasTried = true;
            accumulator = 0;
            RefreshPose();
        }

        public void DragTo(double targetX) => Model.DragTo(targetX);

        public void EndDrag()
        {
            pointerDragging = false;
            Model?.EndDrag();
        }

        public void ResetExperiment()
        {
            EndDrag();
            Model.Reset();
            accumulator = 0;
            RefreshPose();
            RefreshInterface();
        }

        public void Nudge()
        {
            Model.Nudge();
            hasTried = true;
        }

        void RefreshPose()
        {
            if (stage != ExperienceStage.Lesson)
            {
                RefreshWelcomePose();
                RefreshConceptVisuals();
                return;
            }
            cart.localPosition = new Vector3((float)Model.X, 0, 0);
            pole.localRotation = Quaternion.Euler(0, 0, -(float)(Model.Theta * Mathf.Rad2Deg));
            float wheelRotation = -(float)Model.X / .095f * Mathf.Rad2Deg;
            leftWheel.localRotation = rightWheel.localRotation = Quaternion.Euler(0, 0, wheelRotation);
            cartMaterial.color = Color.Lerp(cartBaseColor, Color.Lerp(cartBaseColor, Color.white, .12f), hoverAmount);
            cueAmount = Mathf.MoveTowards(cueAmount, hasTried ? 0 : 1, Time.unscaledDeltaTime * 4f);
            var cueColor = new Color(.06f, .44f, .86f, cueAmount * .42f);
            leftCue.startColor = leftCue.endColor = rightCue.startColor = rightCue.endColor = cueColor;
            RefreshConceptVisuals();
        }

        void RefreshInterface()
        {
            appearanceTime += Time.unscaledDeltaTime;
            float arrival = Mathf.SmoothStep(0, 1, Mathf.Clamp01(appearanceTime / .45f));
            hero.style.opacity = arrival;
            footer.style.opacity = arrival;
            if (wasFallen != Model.HasFallen)
            {
                wasFallen = Model.HasFallen;
                headline.text = wasFallen ? "倒下了，也没关系。" : "抓住小车，\n试着接住杆。";
                guidance.text = wasFallen ? "重新抓住小车，就能再试。" : "不急，先感受它的变化。";
            }
            nudgeButton.SetEnabled(!Model.HasFallen);
        }

        void OnApplicationFocus(bool focused) { if (!focused) { EndDrag(); SaveSession(); } }
        void OnApplicationPause(bool paused) { if (paused) { EndDrag(); SaveSession(); } }
        void OnApplicationQuit() { EndDrag(); SaveSession(); }
        void OnDisable() { EndDrag(); }
        void OnDestroy()
        {
            updater?.Dispose();
            settingsPanel?.Dispose();
            studio?.Dispose();
            foreach (var asset in ownedAssets) if (asset != null) Destroy(asset);
        }

        static Color Hex(string value)
        {
            ColorUtility.TryParseHtmlString("#" + value, out Color color);
            return color;
        }
    }
}
