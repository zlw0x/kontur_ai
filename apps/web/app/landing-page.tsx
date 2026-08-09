"use client";

import StlPreview from "./stl-preview";

type LandingPageProps = { onOpenStudio?: () => void };
type LandingIconName = "check" | "cube" | "download" | "image" | "message" | "play" | "ruler" | "upload";

export default function LandingPage({ onOpenStudio }: LandingPageProps) {
  return (
    <main className="landing-page">
      <header className="landing-nav">
        <a className="landing-brand" href="/" aria-label="KONTUR — на главную">
          <span className="landing-logo"><LandingIcon name="cube" /></span>
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
            <a className="hero-secondary" href="#how-it-works"><LandingIcon name="play" /> Посмотреть как это работает</a>
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
              <div className="demo-panel-bar">
                <span className="panel-index">01</span>
                <span><b>Исходный чертёж</b><small>JPG · готов к анализу</small></span>
                <i><LandingIcon name="image" /></i>
              </div>
              <div className="rough-drawing sketch-photo">
                <img src="/pencil-part-sketch-v2.webp" alt="Неровный карандашный чертёж детали, выполненный от руки" />
                <span className="paper-scan-line" aria-hidden="true" />
              </div>
              <div className="demo-panel-action">
                <span><b>part-sketch.jpg</b><small>Изображение детали</small></span>
                <span className="demo-action-visual" aria-hidden="true"><LandingIcon name="upload" /> Загрузить</span>
              </div>
            </div>
            <div className="conversion-arrow" aria-hidden="true"><span><Arrow /></span><small>AI</small></div>
            <div className="result-panel">
              <div className="demo-panel-bar">
                <span className="panel-index">02</span>
                <span><b>Готовая 3D-модель</b><small>STEP · STL</small></span>
                <i className="panel-ready"><LandingIcon name="check" /></i>
              </div>
              <div className="demo-model">
                <StlPreview local transparent material="cad" dimensions={{ length: 80, width: 40, height: 12 }} ready />
              </div>
              <div className="demo-panel-action">
                <span><b>Модель проверена</b><small>80 × 40 × 12 мм</small></span>
                <span className="demo-action-visual" aria-hidden="true"><LandingIcon name="download" /> Скачать</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-stats" aria-label="Преимущества KONTUR">
        <div><strong>1</strong><span>чертёж<br /><small>на входе</small></span></div>
        <div><strong>3D</strong><span>готовая модель<br /><small>на выходе</small></span></div>
        {/*
          This said "100% контроль ключевых размеров", and the service cannot back a
          percentage. What it can back is the mechanism: every dimension the document
          declares is measured on the exported file and compared, and the reading is
          compared against the compilation. Neither of those is 100% of anything — a
          drawing misread the same way twice passes both — so the claim now names what
          happens instead of scoring it.
        */}
        <div><strong>STEP</strong><span>каждый заявленный размер<br /><small>измеряется на готовом файле</small></span></div>
        <p>Создано для тех, кто<br /><b>проектирует, проверяет, создаёт.</b></p>
      </section>

      <section className="how-section" id="how-it-works">
        <div className="section-intro">
          <span className="eyebrow lime">Простой путь к результату</span>
          <h2>Идея не должна ждать<br /><em>идеального чертежа.</em></h2>
          <p>KONTUR берет на себя рутинную часть работы, оставляя вам контроль над тем, что действительно важно.</p>
        </div>
        <div className="how-grid">
          <article className="how-card first"><span className="card-number">01</span><span className="card-icon"><LandingIcon name="upload" /></span><h3>Загрузите чертёж</h3><p>Фото, скан или набросок с размерами — система разберётся с исходным материалом.</p><span className="card-link">PNG или JPG <Arrow /></span></article>
          <article className="how-card"><span className="card-number">02</span><span className="card-icon cyan-icon"><LandingIcon name="message" /></span><h3>Подтвердите важное</h3><p>Если размер или обозначение неочевидны, KONTUR задаст короткий уточняющий вопрос.</p><span className="card-link">Вы всегда в контроле <Arrow /></span></article>
          <article className="how-card featured"><span className="card-number">03</span><span className="card-icon"><LandingIcon name="cube" /></span><h3>Получите 3D-модель</h3><p>Готовая геометрия, которую можно открыть в CAD-системе или передать в производство.</p><span className="card-link">STEP · STL <Arrow /></span></article>
        </div>
      </section>

      <section className="capabilities-section" id="capabilities">
        <div className="capability-visual" aria-label="Интерфейс KONTUR во время обработки чертежа">
          <div className="capability-process">
            <div className="process-topbar">
              <div><span className="process-mark"><LandingIcon name="cube" /></span><span><b>Деталь 01</b><small>По загруженному эскизу</small></span></div>
              <span className="process-live"><i /> В процессе</span>
            </div>
            <div className="process-body">
              <div className="process-steps">
                <div className="done"><span><LandingIcon name="check" /></span><p><b>Чертёж принят</b><small>Изображение готово к анализу</small></p></div>
                <div className="done"><span><LandingIcon name="check" /></span><p><b>Размеры распознаны</b><small>80 × 40 × 12 мм</small></p></div>
                <div className="active"><span>03</span><p><b>Уточнение геометрии</b><small>Нужен один ответ</small></p></div>
                <div><span>04</span><p><b>Построение модели</b><small>Следующий этап</small></p></div>
              </div>
              <div className="process-question">
                <div className="question-head"><span><LandingIcon name="message" /></span><div><b>KONTUR уточняет</b><small>Чтобы сохранить точность</small></div></div>
                <p>Диаметр центрального отверстия — <strong>8 мм</strong>?</p>
                <div className="detected-values"><span>Длина <b>80</b></span><span>Ширина <b>40</b></span><span>Высота <b>12</b></span></div>
                <div className="question-actions"><span>Да, верно</span><span>Изменить</span></div>
              </div>
            </div>
            <div className="process-footer"><span>Подготовка точной геометрии</span><b>68%</b><i><span /></i></div>
          </div>
        </div>
        <div className="capability-copy"><span className="eyebrow cyan">Всё необходимое — внутри</span><h2>Меньше ручной работы.<br /><em>Больше точных решений.</em></h2><p>От первой идеи до понятной геометрии — в одном аккуратном рабочем процессе.</p><div className="capability-list"><div><span><LandingIcon name="ruler" /></span><b>Распознаёт размеры</b><small>Считывает обозначения и габариты с изображения.</small></div><div><span><LandingIcon name="message" /></span><b>Уточняет, когда нужно</b><small>Не делает предположений там, где важна точность.</small></div><div><span><LandingIcon name="download" /></span><b>Отдаёт в привычном формате</b><small>Файлы для CAD, производства и дальнейшей работы.</small></div></div></div>
      </section>

      <section className="workflow-section" id="workflow">
        <div className="workflow-quote"><span className="quote-mark">“</span><blockquote>Хороший инструмент не заменяет инженера.<br /><em>Он освобождает его время для инженерной работы.</em></blockquote><span className="quote-line" /></div>
        <div className="workflow-cta"><span className="eyebrow lime">Начните с одной детали</span><h2>Ваш следующий<br /><em>проект — уже здесь.</em></h2><a className="hero-primary" href="/studio" onClick={onOpenStudio}>Открыть KONTUR <Arrow /></a></div>
      </section>

      <footer className="landing-footer"><a className="landing-brand" href="/"><span className="landing-logo"><LandingIcon name="cube" /></span><span><b>KONTUR</b><small>3D по чертежу</small></span></a><span>Точные модели начинаются с понятной идеи.</span><span>© 2026 KONTUR</span></footer>
    </main>
  );
}

function Arrow() {
  return <svg className="arrow-icon" viewBox="0 0 24 24" fill="none"><path d="M4 12h15m-5-5 5 5-5 5" /></svg>;
}

function LandingIcon({ name }: { name: LandingIconName }) {
  const common = { className: "landing-icon", viewBox: "0 0 24 24", fill: "none", "aria-hidden": true };

  if (name === "check") return <svg {...common}><path d="m5 12.5 4.2 4.2L19 7" /></svg>;
  if (name === "upload") return <svg {...common}><path d="M12 16V4m-5 5 5-5 5 5M5 15v4h14v-4" /></svg>;
  if (name === "download") return <svg {...common}><path d="M12 4v11m-4-4 4 4 4-4M5 19h14" /></svg>;
  if (name === "cube") return <svg {...common}><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Zm-7.6 4.7L12 12l7.6-4.3M12 12v9" /></svg>;
  if (name === "image") return <svg {...common}><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><circle cx="9" cy="10" r="1.5" /><path d="m4.5 17 4.5-4 3.5 3 2.5-2 4.5 3.5" /></svg>;
  if (name === "message") return <svg {...common}><path d="M5 5h14v11H9l-4 4V5Z" /><path d="M9 9h6M9 12h4" /></svg>;
  if (name === "play") return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="m10 8 6 4-6 4V8Z" /></svg>;
  return <svg {...common}><path d="M5 17.5 17.5 5 20 7.5 7.5 20 5 17.5Z" /><path d="m9 16 2 2m1-5 2 2m1-5 2 2" /></svg>;
}
