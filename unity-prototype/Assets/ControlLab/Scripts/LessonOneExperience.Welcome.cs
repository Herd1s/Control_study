using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.UIElements;

namespace ControlLab.UnityPrototype
{
    public sealed partial class LessonOneExperience
    {
        enum ExperienceStage { Studio, Arriving, Lesson }
        ExperienceStage stage = ExperienceStage.Studio;
        const float StudioX = -1.65f;
        const float StudioScale = 2.2f;
        const float ArrivalDuration = 2.6f;
        CartStudio studio;
        Material upperMaterial, skinMaterial;
        Color cartBaseColor = new Color(8f / 255f, 120f / 255f, 232f / 255f);
        string cartName = "我的小车", cartColor = "#0878E8";
        Label arrivalTitle;
        VisualElement studioDecor;
        Label studioHeading, studioName;
        float arrivalTime, arrivalWheelAngle, previousArrivalX;
        bool customizingCart, customizationExplanation;
        int customizationConcept;

        public string FlowStage => stage.ToString();
        public CartStudio Studio => studio;
        public string CartName => cartName;
        public string CartColor => cartColor;
        public float VisualCartX => cart == null ? 0 : cart.localPosition.x;
        public float VisualCartScale => cart == null ? 1 : cart.localScale.x;
        public bool CustomizingCart => customizingCart;

        void InitializeWelcome()
        {
            CreateSkinSurface();
            var caption = overlay.Q<Label>("lesson-caption");
            caption.enableRichText = false;
            caption.style.maxWidth = 260;
            caption.style.overflow = Overflow.Hidden;
            caption.style.textOverflow = TextOverflow.Ellipsis;
            caption.style.whiteSpace = WhiteSpace.NoWrap;
            var customize = new Button(ShowStudio) { name = "customize-cart", text = "装扮小车" };
            customize.AddToClassList("pill");
            customize.AddToClassList("secondary");
            customize.style.height = 36;
            customize.style.minWidth = 118;
            customize.style.paddingLeft = customize.style.paddingRight = 12;
            overlay.Q<VisualElement>("topbar").Add(customize);

            arrivalTitle = new Label("下一站，第一章") { name = "arrival-title", pickingMode = PickingMode.Ignore };
            arrivalTitle.style.position = Position.Absolute;
            arrivalTitle.style.top = 105;
            arrivalTitle.style.left = arrivalTitle.style.right = 0;
            arrivalTitle.style.fontSize = 30;
            arrivalTitle.style.unityFontStyleAndWeight = FontStyle.Bold;
            arrivalTitle.style.unityTextAlign = TextAnchor.MiddleCenter;
            arrivalTitle.style.display = DisplayStyle.None;
            overlay.Add(arrivalTitle);
            studioDecor = new VisualElement { name = "studio-preview-decor", pickingMode = PickingMode.Ignore };
            studioDecor.style.position = Position.Absolute;
            studioDecor.style.left = studioDecor.style.right = studioDecor.style.top = studioDecor.style.bottom = 0;
            var brand = new Label("ControlLab") { pickingMode = PickingMode.Ignore };
            brand.style.position = Position.Absolute;
            brand.style.left = 38; brand.style.top = 30;
            brand.style.fontSize = 22; brand.style.unityFontStyleAndWeight = FontStyle.Bold;
            studioDecor.Add(brand);
            studioHeading = new Label("先造一辆\n属于你的小车。") { name = "studio-preview-title", pickingMode = PickingMode.Ignore };
            studioHeading.style.position = Position.Absolute;
            studioHeading.style.unityTextAlign = TextAnchor.MiddleCenter;
            studioHeading.style.unityFontStyleAndWeight = FontStyle.Bold;
            studioDecor.Add(studioHeading);
            studioName = new Label(cartName) { name = "studio-preview-name", pickingMode = PickingMode.Ignore, enableRichText = false };
            studioName.style.position = Position.Absolute;
            studioName.style.fontSize = 24;
            studioName.style.unityTextAlign = TextAnchor.MiddleCenter;
            studioName.style.overflow = Overflow.Hidden;
            studioName.style.textOverflow = TextOverflow.Ellipsis;
            studioName.style.whiteSpace = WhiteSpace.NoWrap;
            studioDecor.Add(studioName);
            overlay.Add(studioDecor);
            studio = new CartStudio(overlay, ApplyCartAppearance, CompleteStudio);
            ShowStudio();
        }

        void CreateSkinSurface()
        {
            var skin = GameObject.CreatePrimitive(PrimitiveType.Quad);
            skin.name = "Custom cart side skin";
            skin.transform.SetParent(cart, false);
            skin.transform.localPosition = new Vector3(0, .35f, -.252f);
            skin.transform.localScale = new Vector3(.60f, .21f, 1);
            RemoveCollider(skin);
            var shader = Resources.Load<Shader>("CartSkin");
            if (shader == null) throw new InvalidOperationException("CartSkin shader is missing.");
            skinMaterial = new Material(shader) { name = "Student side skin" };
            ownedAssets.Add(skinMaterial);
            var renderer = skin.GetComponent<Renderer>();
            renderer.sharedMaterial = skinMaterial;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
        }

        void ApplyCartAppearance(CartProfile profile, Texture2D skin)
        {
            cartName = CartProfileStore.SanitizeName(profile.displayName);
            cartColor = CartProfileStore.NormalizeColor(profile.bodyColor);
            ColorUtility.TryParseHtmlString(cartColor, out cartBaseColor);
            cartMaterial.color = cartBaseColor;
            upperMaterial.color = Color.Lerp(cartBaseColor, Color.white, .45f);
            skinMaterial.mainTexture = skin;
            overlay.Q<Label>("lesson-caption").text = "第一章 · " + cartName;
            if (studioName != null) studioName.text = cartName;
            settingsPanel?.SetCart(cartName, cartBaseColor, skin);
        }

        public void ShowStudio()
        {
            if (studio == null) return;
            EndDrag();
            if (stage == ExperienceStage.Lesson)
            {
                SaveLearningProgress();
                customizingCart = true;
                customizationConcept = activeConcept;
                customizationExplanation = explanationOpen;
            }
            // Editing appearance pauses the existing physical episode; it is not a reset.
            if (!customizingCart) { Model.Reset(); accumulator = 0; }
            explanationOpen = false;
            explanation.style.display = DisplayStyle.None;
            explainButton.text = "为什么会倒？";
            explainButton.EnableInClassList("selected", false);
            stage = ExperienceStage.Studio;
            SetLessonInterface(false);
            arrivalTitle.style.display = DisplayStyle.None;
            studio.SetCustomizeMode(customizingCart);
            studio.Show();
            studioHeading.text = customizingCart ? "换个外观，\n继续探索。" : "先造一辆\n属于你的小车。";
            studioDecor.style.display = DisplayStyle.Flex;
            LayoutStudioDecor();
            RefreshWelcomePose();
            RefreshConceptVisuals();
            SaveLearningProgress();
        }

        void CompleteStudio()
        {
            if (!customizingCart) { BeginArrival(); return; }
            customizingCart = false;
            stage = ExperienceStage.Lesson;
            studio.Hide();
            studioDecor.style.display = DisplayStyle.None;
            cart.localScale = Vector3.one;
            pole.gameObject.SetActive(true);
            pole.localScale = Vector3.one;
            explanationOpen = customizationExplanation;
            SetLessonInterface(true);
            explanation.style.display = explanationOpen ? DisplayStyle.Flex : DisplayStyle.None;
            hero.style.display = explanationOpen ? DisplayStyle.None : DisplayStyle.Flex;
            explainButton.text = explanationOpen ? "收起说明" : "为什么会倒？";
            explainButton.EnableInClassList("selected", explanationOpen);
            SelectConcept(customizationConcept);
            ignorePointerUntilReleased = true;
            RefreshPose();
            RefreshInterface();
            SaveLearningProgress();
        }

        void SetLessonInterface(bool visible)
        {
            var display = visible ? DisplayStyle.Flex : DisplayStyle.None;
            overlay.Q<VisualElement>("topbar").style.display = display;
            hero.style.display = display;
            footer.style.display = display;
            if (!visible) explanation.style.display = DisplayStyle.None;
        }

        void BeginArrival()
        {
            if (stage != ExperienceStage.Studio) return;
            preserveCheckpointOnStudio = false;
            // This is a presentation transition. The physical episode starts only at the centre.
            EndDrag();
            Model.Reset();
            accumulator = 0;
            studio.Hide();
            studioDecor.style.display = DisplayStyle.None;
            stage = ExperienceStage.Arriving;
            arrivalTime = arrivalWheelAngle = 0;
            previousArrivalX = StudioX;
            arrivalTitle.style.display = DisplayStyle.Flex;
            arrivalTitle.style.opacity = 0;
            SaveLearningProgress();
        }

        void TickWelcome()
        {
            studio?.Tick();
            if (stage == ExperienceStage.Studio) LayoutStudioDecor();
            if (stage == ExperienceStage.Arriving)
            {
                arrivalTime += Mathf.Min(Time.unscaledDeltaTime, .1f);
                RefreshWelcomePose();
                if (arrivalTime >= ArrivalDuration) EnterFirstChapter();
            }
            else if (stage == ExperienceStage.Studio) RefreshWelcomePose();
        }

        void LayoutStudioDecor()
        {
            if (studioHeading == null) return;
            bool compact = Screen.width < 1000 || Screen.height < 700;
            float panelLeft = Screen.width - (compact ? 404 : 450);
            float width = Mathf.Max(1, panelLeft - 48);
            studioHeading.style.left = studioName.style.left = 24;
            studioHeading.style.width = studioName.style.width = width;
            studioHeading.style.top = compact ? 112 : 135;
            studioHeading.style.fontSize = compact ? 28 : 36;
            studioName.style.top = Screen.height * .75f;
        }

        void RefreshWelcomePose()
        {
            if (cart == null) return;
            if (stage == ExperienceStage.Studio)
            {
                cart.localPosition = new Vector3(StudioX, .125f * (1 - StudioScale), 0);
                cart.localScale = Vector3.one * StudioScale;
                pole.gameObject.SetActive(false);
                leftWheel.localRotation = rightWheel.localRotation = Quaternion.identity;
            }
            else if (stage == ExperienceStage.Arriving)
            {
                float t = Mathf.Clamp01(arrivalTime / ArrivalDuration);
                float eased = t * t * t * (10 + t * (-15 + 6 * t));
                float size = Mathf.Lerp(StudioScale, 1, eased);
                float x = Mathf.Lerp(StudioX, 0, eased);
                arrivalWheelAngle -= (x - previousArrivalX) / (.095f * size) * Mathf.Rad2Deg;
                previousArrivalX = x;
                cart.localPosition = new Vector3(x, .125f * (1 - size), 0);
                cart.localScale = Vector3.one * size;
                leftWheel.localRotation = rightWheel.localRotation = Quaternion.Euler(0, 0, arrivalWheelAngle);
                pole.gameObject.SetActive(true);
                pole.localRotation = Quaternion.identity;
                pole.localScale = new Vector3(1, Mathf.SmoothStep(0, 1, Mathf.InverseLerp(.15f, .8f, t)), 1);
                arrivalTitle.style.opacity = Mathf.SmoothStep(0, 1, Mathf.Clamp01(t * 5)) *
                    (1 - Mathf.SmoothStep(0, 1, Mathf.InverseLerp(.8f, 1, t)));
            }
            cartMaterial.color = cartBaseColor;
        }

        void EnterFirstChapter()
        {
            stage = ExperienceStage.Lesson;
            studio.Hide();
            studioDecor.style.display = DisplayStyle.None;
            arrivalTitle.style.display = DisplayStyle.None;
            cart.localScale = Vector3.one;
            pole.gameObject.SetActive(true);
            pole.localScale = Vector3.one;
            Model.Reset();
            accumulator = 0;
            hoverAmount = 0;
            hasTried = wasFallen = false;
            cueAmount = 1;
            appearanceTime = 0;
            headline.text = "抓住小车，\n试着接住杆。";
            guidance.text = "不急，先感受它的变化。";
            SetLessonInterface(true);
            RefreshPose();
            RefreshInterface();
            SaveLearningProgress();
        }
    }
}
