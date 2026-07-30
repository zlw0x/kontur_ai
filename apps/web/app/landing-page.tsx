"use client";

import { useState } from "react";
import StlPreview from "./stl-preview";

type LandingPageProps = { onOpenStudio?: () => void };

export default function LandingPage({ onOpenStudio }: LandingPageProps) {
  const [demoMode, setDemoMode] = useState<"drawing" | "model">("model");

  return (
    <main className="landing-page">
      <header className="landing-nav">
        <a className="landing-brand" href="/" aria-label="KONTUR — на главную">
          <span className="landing-logo"><span /><span /><span /></span>
          <span><b>KONTUR</b><small>3D по чертежу</small></span>
        </a>
        <nav className="landing-links" aria-label="Основная навигация">
          <a href="#how-it-works">Как это работает</a>
          <a href="#capabilities">Возможности</a>
          <a href="#workflow">Для инженеров</a>
        </nav>
        <a className="landing-nav-cta" href="/studio" onClick={onOpenStudio}>
          Открыть студию <Arrow />
        </a>
      </header>

      <section className="landing-hero">
        <div className="hero-copy">
          <div className="hero-kicker"><i /> CAD-автоматизация нового поколения</div>
          <h1>От чертежа<br />к <em>точной модели.</em></h1>
          <p className="hero-lede">
            Загрузите даже неидеальный технический рисунок. KONTUR распознает размеры,
            уточнит важное и соберёт готовую 3D-модель для работы.
          </p>
          <div className="hero-actions">
            <a className="hero-primary" href="/studio" onClick={onOpenStudio}>
              Создать 3D-модель <Arrow />
            </a>
            <a className="hero-secondary" href="#how-it-works"><span>◉</span> Посмотреть как это работает</a>
          </div>
          <div className="hero-proof">
            <div className="proof-avatars"><i>А</i><i>М</i><i>И</i><i>+</i></div>
            <span><b>Инженеры уже используют KONTUR</b><small>для быстрых итераций и проверки идей</small></span>
          </div>
        </div>

        <div className="hero-visual" aria-label="Демонстрация преобразования чертежа в 3D-модель">
          <div className="hero-visual-glow" />
          <div className="demo-header">
            <div><span className="live-dot" /> Живая демонстрация</div>
            <span>01 / 02</span>
          </div>
          <div className="demo-stage">
            <div className="source-panel">
              <div className="demo-panel-label"><span>01</span><b>Исходный чертёж</b><small>даже если от руки</small></div>
              <div className="rough-drawing sketch-photo">
                <img src="/pencil-part-sketch.webp" alt="Непрофессиональный карандашный чертёж детали на листе бумаги" />
                <span className="paper-scan-line" aria-hidden="true" />
              </div>
              <div className="source-caption"><span className="sketch-icon">⌁</span><span><b>part-sketch.jpg</b><small>Загружено только что</small></span><i>✓</i></div>
            </div>
            <div className="conversion-arrow"><span><Arrow /></span><small>распознаём<br />и строим</small></div>
            <div className={`result-panel demo-${demoMode}`}>
              <div className="demo-panel-label"><span>02</span><b>Готовая 3D-модель</b><small>точная геометрия</small></div>
              <div className="demo-model">
                <StlPreview local material="aluminum" dimensions={{ length: 80, width: 40, height: 12 }} ready />
              </div>
              <div className="result-caption"><span className="verified-icon">✓</span><span><b>Модель проверена</b><small>80 × 40 × 12 мм · 4 отверстия</small></span></div>
            </div>
          </div>
          <div className="demo-switcher" role="tablist" aria-label="Этап демонстрации">
            <button className={demoMode === "drawing" ? "active" : ""} type="button" onClick={() => setDemoMode("drawing")}>Чертёж</button>
            <span />
            <button className={demoMode === "model" ? "active" : ""} type="button" onClick={() => setDemoMode("model")}>3D-модель</button>
          </div>
        </div>
      </section>

      <section className="landing-stats" aria-label="Преимущества KONTUR">
        <div><strong>1</strong><span>чертёж<br /><small>на входе</small></span></div>
        <div><strong>3D</strong><span>готовая модель<br /><small>на выходе</small></span></div>
        <div><strong>100%</strong><span>контроль<br /><small>ключевых размеров</small></span></div>
        <p>Создано для тех, кто<br /><b>проектирует, проверяет, создаёт.</b></p>
      </section>

      <section className="how-section" id="how-it-works">
        <div className="section-intro">
          <span className="eyebrow lime">Простой путь к результату</span>
          <h2>Идея не должна ждать<br /><em>идеального чертежа.</em></h2>
          <p>KONTUR берет на себя рутинную часть работы, оставляя вам контроль над тем, что действительно важно.</p>
        </div>
        <div className="how-grid">
          <article className="how-card first"><span className="card-number">01</span><span className="card-icon upload-icon-css"><i /></span><h3>Загрузите чертёж</h3><p>Фото, скан или набросок с размерами — система разберётся с исходным материалом.</p><span className="card-link">PNG или JPG <Arrow /></span></article>
          <article className="how-card"><span className="card-number">02</span><span className="card-icon question-icon-css">?</span><h3>Подтвердите важное</h3><p>Если размер или обозначение неочевидны, KONTUR задаст короткий уточняющий вопрос.</p><span className="card-link">Вы всегда в контроле <Arrow /></span></article>
          <article className="how-card featured"><span className="card-number">03</span><span className="card-icon model-icon-css"><i /><i /><i /></span><h3>Получите 3D-модель</h3><p>Готовая геометрия, которую можно открыть в CAD-системе или передать в производство.</p><span className="card-link">STEP · STL · M3D <Arrow /></span></article>
        </div>
      </section>

      <section className="capabilities-section" id="capabilities">
        <div className="capability-visual"><div className="orbit-ring ring-one" /><div className="orbit-ring ring-two" /><div className="capability-object"><i /><i /><i /></div><span className="floating-tag tag-one">Ø 8</span><span className="floating-tag tag-two">80 мм</span><span className="floating-tag tag-three">✓ Проверено</span></div>
        <div className="capability-copy"><span className="eyebrow cyan">Всё необходимое — внутри</span><h2>Меньше ручной работы.<br /><em>Больше точных решений.</em></h2><p>От первой идеи до понятной геометрии — в одном аккуратном рабочем процессе.</p><div className="capability-list"><div><span>⌗</span><b>Распознаёт размеры</b><small>Считывает обозначения и габариты с изображения.</small></div><div><span>✦</span><b>Уточняет, когда нужно</b><small>Не делает предположений там, где важна точность.</small></div><div><span>↗</span><b>Отдаёт в привычном формате</b><small>Файлы для CAD, производства и дальнейшей работы.</small></div></div></div>
      </section>

      <section className="workflow-section" id="workflow">
        <div className="workflow-quote"><span className="quote-mark">“</span><blockquote>Хороший инструмент не заменяет инженера.<br /><em>Он освобождает его время для инженерной работы.</em></blockquote><span className="quote-line" /></div>
        <div className="workflow-cta"><span className="eyebrow lime">Начните с одной детали</span><h2>Ваш следующий<br /><em>проект — уже здесь.</em></h2><a className="hero-primary" href="/studio" onClick={onOpenStudio}>Открыть KONTUR <Arrow /></a></div>
      </section>

      <footer className="landing-footer"><a className="landing-brand" href="/"><span className="landing-logo"><span /><span /><span /></span><span><b>KONTUR</b><small>3D по чертежу</small></span></a><span>Точные модели начинаются с понятной идеи.</span><span>© 2026 KONTUR</span></footer>
    </main>
  );
}

function Arrow() {
  return <svg className="arrow-icon" viewBox="0 0 24 24" fill="none"><path d="M4 12h15m-5-5 5 5-5 5" /></svg>;
}
