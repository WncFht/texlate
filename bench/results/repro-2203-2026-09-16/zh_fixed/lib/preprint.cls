% Version 1.5.0
% Last update: 02 Feb 2024
% Requirements: TeX Live \geq 2019
% Christian Saemann (c.saemann@hw.ac.uk)
% Martin Wolf (m.wolf@surrey.ac.uk)

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{lib/preprint}

%
% Class
%

\LoadClass[
	a4paper,
	11pt
]{article}

%
% Packages for declaring options
%

\RequirePackage{etoolbox}
%\RequirePackage{kvoptions-patch} % No longer works in TeXLive 2020
\RequirePackage{xkeyval}
\RequirePackage{xkvltxp} % This replaces the kvoptions-patch; see above

%
% Declare options
%

\newif\if@british\@britishfalse
\DeclareOptionX{british}{\@britishtrue}

\newif\if@compression\@compressionfalse
\DeclareOptionX{compression}{\@compressiontrue}

\newif\if@contents\@contentsfalse
\DeclareOptionX{contents}{\@contentstrue}

\newif\if@draft\@draftfalse
\DeclareOptionX{draft-mode}{\@drafttrue}

\newcommand{\@references}{}
\DeclareOptionX{references}[]{\renewcommand{\@references}{#1}}

\newcommand{\@custompackages}{}
\DeclareOptionX{custom-packages}[]{\renewcommand{\@custompackages}{#1}}

\newcommand\Authfont{\normalfont}
\newcommand\Affilfont{\normalfont}
\DeclareOptionX{auth-sc}{\renewcommand\Authfont{\scshape}}
\DeclareOptionX{auth-lg}{\renewcommand\Authfont{\large}}
\DeclareOptionX{affil-sl}{\renewcommand\Affilfont{\slshape}}
\DeclareOptionX{affil-it}{\renewcommand\Affilfont{\itshape}}

\DeclareOptionX*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptionsX\relax

%
% Required packages
%

\RequirePackage{xcolor}
\definecolor{MyDarkBlue}{rgb}{0.15,0.25,0.45}
\RequirePackage[
	perpage, % reset footnote counter each page
	symbol
]{footmisc}
\RequirePackage{adjustbox}
\RequirePackage{array}
\RequirePackage{enumerate}
\RequirePackage{soul} % for linebreak in underline
\RequirePackage[
	textwidth=430pt,
	textheight=630pt,
	centering
]{geometry}
\RequirePackage[
	colorlinks=true,
    citecolor=MyDarkBlue,
    linkcolor=MyDarkBlue,
    urlcolor=MyDarkBlue,
    pdfauthor={},
    pdftitle={},
    pdfsubject={},
    breaklinks=true,
    linktocpage=true,
    hypertexnames=false,
    pdflang={en-GB}
]{hyperref}
\RequirePackage{ifthen}
\RequirePackage{pgffor}


\RequirePackage[
	nosort,
	noadjust
]{cite}
\RequirePackage{orcidlink}

% Math Tools; needs to sit here
\RequirePackage{mathtools}

% Math Fonts
\newcommand\hmmax{0}
\newcommand\bmmax{0}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{amsthm}
\RequirePackage{amsfonts}
\RequirePackage{bbm}
\RequirePackage{bm}
\let\oldsquare\square % preserve \square from amssymb, which mathabx overwrites
\RequirePackage{mathabx}
\RequirePackage{mathrsfs}
\RequirePackage{slashed}

% Tikz Settings 
\RequirePackage{tikz}
	\usetikzlibrary{arrows,cd}
	\usetikzlibrary{decorations.markings}
	\usetikzlibrary{decorations.pathmorphing}
	\usetikzlibrary{patterns}
	\usetikzlibrary{positioning}
	\usetikzlibrary{shadows.blur}
	% Arrow heads
	\tikzset{>=stealth}
    \tikzcdset{arrow style=tikz}

% Referencing; needs to be after amsmath
\RequirePackage{aliascnt}
\RequirePackage[
    capitalise,
    nameinlink,
    noabbrev
]{cleveref}
\newcommand{\creflastconjunction}{, and\nobreakspace}
\newcommand{\creflastgroupconjunction}{, and\nobreakspace}
\let\oldref\ref
\AtBeginDocument{\renewcommand{\ref}[1]{\cref{#1}}}
\AtBeginDocument{\renewcommand{\eqref}[1]{{\rm (\oldref{#1})}}}

%
% Optional packages
%

\if@british
	\RequirePackage[british]{babel} % dates in British format
\fi

%
% Custom packages
%

\renewcommand*{\do}[1]{\RequirePackage{#1}}
\dolistloop{\@custompackages}

%
% Commands
%

\input{lib/characters.tex}
\input{lib/commands.tex}
\input{lib/hyphenation.tex}

%
% Options
%

% Abstract
\def\abstract#1{\def\@abstract{#1}}

% Acknowledgements
\def\acknowledgements#1{\def\@acknowledgements{#1}}
\def\@acknowledgementslist{}
\renewcommand\@acknowledgementslist{%
	\ifdefined\@acknowledgements
		\if@british
			\section*{Acknowledgements}
			\addcontentsline{toc}{section}{Acknowledgements}
		\else
			\section*{Acknowledgments}
			\addcontentsline{toc}{section}{Acknowledgments}
		\fi
		\@acknowledgements
	\fi
}

% Data and licence management
\def\datalicencemanagement#1{\def\@datalicencemanagement{#1}}
\def\@datalicencemanagementlist{}
\renewcommand\@datalicencemanagementlist{%
	\ifdefined\@datalicencemanagement
		\section*{Data and Licence Management}
		\addcontentsline{toc}{section}{Data and Licence Management}
		\@datalicencemanagement
	\fi
}

% Date
\def\date#1{\def\@date{#1}}

% Emails
\def\email#1{\def\@email{#1}}
\def\@emaillist{}
\renewcommand\@emaillist{%
	~\footnote{%
		{\itshape E-mail addresses: }%
		\foreach[count=\i] \n in \@email {%
			\ifnum\i=1
				\href{mailto:\n}{\ttfamily\n}%
			\else
				, \href{mailto:\n}{\ttfamily\n}%
			\fi
		}%
	}%
}

% Preprint Numbers
\def\preprint#1{\def\@preprint{#1}}
\def\@preprintlist{}
\renewcommand\@preprintlist{%
	\begin{flushright}
		\foreach[count=\i] \n in \@preprint {%
			\ifnum\i=1
				\n%
			\else
				\\\n%
			\fi
		}%
	\end{flushright}
}

% Title
\def\title#1{\def\@title{#1}}

%
% Authors, affiliations, and emails
%

\newcommand\Authsep{, }
\newcommand\Authands{, and }
\newcommand\Authand{ and }
\newlength{\affilsep}\setlength{\affilsep}{.5cm}
\newlength{\@affilsep}

\newcounter{Maxaffil}
\setcounter{Maxaffil}{\maxdimen}

\newcounter{authors}
\newcounter{affil}

\newif\ifnewaffil\newaffiltrue
\newif\ifnewemail\newemailtrue

\newcommand\AB@authnote[1]{\textsuperscript{\normalfont\,#1}}
\newcommand\AB@affilnote[1]{\textsuperscript{\normalfont\,#1}}
\providecommand\textsuperscript[1]{$^{#1}$}
\newcommand\AB@blk@and{\protect\Authfont\protect\AB@setsep}
\newcommand\AB@pand{\protect\and\protect\Authfont\protect\AB@setsep}
\@namedef{@sep1}{}
\@namedef{@sep2}{\Authand}

\newcommand\AB@affilsep{\protect\Affilfont}
\newcommand\AB@affilsepx{\protect\\[\if@compression 0\else .5\fi cm]\protect\Affilfont} % separation between affiliation

\newcommand\AB@setsep{\setlength{\@affilsep}{\affilsep}}
\newcommand\AB@resetsep{\setlength{\@affilsep}{\z@}}

\newcommand\AB@authlist{} 
\newcommand\AB@affillist{} 

\newcommand\AB@authors{} 
\newcommand\AB@empty{}

% Set the authors
\xdef\AB@author{\noexpand\AB@blk@and\@author}
\renewcommand\author[2][]{%
	\ifnewaffil\addtocounter{affil}{1}%
       	\edef\AB@thenote{\arabic{affil}}
    \fi
    \if\relax#1\relax
    	\def\AB@note{\AB@thenote}
    \else
    	\def\AB@note{#1}%
        \setcounter{Maxaffil}{0}
    \fi
    \ifnum\value{authors}>1\relax
		\@namedef{@sep\number\c@authors}{\Authsep}
	\fi
    \addtocounter{authors}{1}%
    \begingroup
    	\let\protect\@unexpandable@protect 
    	\let\and\AB@pand
        \def\footnote{\protect\footnote}%
        \@temptokena=\expandafter{\AB@authors}{%
        	\def\\{\protect\\[\@affilsep]\protect\Affilfont\protect\AB@resetsep}%
            \xdef\AB@author{\AB@blk@and#2}%
	       	\ifnewaffil\gdef\AB@las{}\gdef\AB@lasx{\protect\Authand}\gdef\AB@as{}%
	           	\xdef\AB@authors{\the\@temptokena\AB@blk@and}%
	       	\else
	          	\xdef\AB@authors{\the\@temptokena\AB@as\AB@au@str}%
	          	\global\let\AB@las\AB@lasx\gdef\AB@lasx{\protect\Authands}%
	          	\gdef\AB@as{\Authsep}%
	       	\fi
	       	\gdef\AB@au@str{#2}%
	    }%
        \@temptokena=\expandafter{\AB@authlist}%
        \let\\=\authorcr\xdef\AB@authlist{%
        	\the\@temptokena\protect\@nameuse{@sep\number\c@authors}\protect\Authfont{#2}\AB@authnote{\AB@note}%
        }%
	\endgroup
	\ifnum\value{authors}>2\relax
		\@namedef{@sep\number\c@authors}{\Authands}
	\fi
    \newaffilfalse
}
\newcommand\authorcr{\protect\\\protect\Authfont\protect\AB@setsep}%

% Set the affiliations
\newcommand\affil[2][]{%
	\newaffiltrue\let\AB@blk@and\AB@pand
	\if\relax#1\relax
		\def\AB@note{\AB@thenote}
	\else
		\def\AB@note{#1}%
        \setcounter{Maxaffil}{0}
	\fi
	\begingroup
		\let\protect\@unexpandable@protect
        \def\footnote{\protect\footnote}%
        \@temptokena=\expandafter{\AB@authors}{%
        	\def\\{\protect\\\protect\Affilfont}%
        	\xdef\AB@temp{#2}%
        }%
     	\xdef\AB@authors{%
     		\the\@temptokena\AB@las\AB@au@str\footnote{{\itshape E-mail address: }\href{mailto:\@email}{\ttfamily\@email}}
     		\protect\\[\affilsep]\protect\Affilfont\AB@temp
     	}%
     	\gdef\AB@las{}\gdef\AB@au@str{}{%
     		\def\\{\protect\\\protect\Affilfont}%
     		\xdef\AB@temp{#2}
     	}%
    	\@temptokena=\expandafter{\AB@affillist}%
    	\xdef\AB@affillist{%
    		\the\@temptokena\AB@affilsep
      		\AB@affilnote{\AB@note}\protect\Affilfont\AB@temp
      	}%
    \endgroup
    \let\AB@affilsep\AB@affilsepx
}

% Set the authors with affiliations and email addresses
\def\@author{}
\renewcommand\@author{%
	\ifx
		\AB@affillist\AB@empty\AB@author
	\else
    	\ifnum\value{affil}>\value{Maxaffil}
    		\def\rlap##1{##1}%
    		\AB@authlist\@emaillist\\[\affilsep]\AB@affillist
    	\else
    		\AB@authors
    	\fi
    \fi
}

%
% Layout
%

\sloppy
\flushbottom
\linespread{1.3}
\setlength{\footnotesep}{3.5mm}

% Section etc
\renewcommand{\section}{%
	\@startsection{section}{1}{\z@}{-3.5ex plus -1ex minus -.2ex}{2.3ex plus .2ex}{\bfseries\mathversion{bold}\large }%
}
\renewcommand{\subsection}{%
	\@startsection{subsection}{2}{\z@}{-3.25ex plus -1ex minus -.2ex}{1.5ex plus .2ex}{\bfseries\mathversion{bold} }%
}
\renewcommand{\subsubsection}{%
	\@startsection{subsubsection}{3}{-2.45ex}{-3.25ex plus -1ex minus -.2ex}{1.5ex plus .2ex}{\itshape }
}
\renewcommand\paragraph{%
	\@startsection{paragraph}{4}{\z@}{3.25ex \@plus1ex \@minus.2ex}{-1em}{\normalfont\normalsize\bfseries\mathversion{bold}}}

\renewcommand{\thesection}{\arabic{section}}
\renewcommand{\thesubsection}{\thesection.\arabic{subsection}}
\renewcommand{\@seccntformat}[1]{\@nameuse{the#1}~~}
\renewcommand{\thesubsubsection}{}

% Table of contents
\setcounter{tocdepth}{2}
\renewcommand*\l@section{
	\def\numberline##1{\hb@xt@\@tempdima{##1.\hfil}}
	\@dottedtocline{1}{0em}{2em}
}
\renewcommand*\l@subsection{
	\def\numberline##1{\hb@xt@\@tempdima{##1.\hfil}}
	\@dottedtocline{2}{2em}{2.4em}
}
\renewcommand*\l@subsubsection{
	\def\numberline##1{\hb@xt@\@tempdima{##1.\hfil}}
	\@dottedtocline{4}{3.8em}{3.7em}
}
\renewcommand\tableofcontents{%
    \section*{\contentsname
        \@mkboth{\MakeUppercase\contentsname}{\MakeUppercase\contentsname}}%
       	{\baselineskip=15pt plus 2pt minus 1pt\@starttoc{toc}}%
}

% Period after section etc, from secdot package
\newcommand{\sectiondot}[1]{%
  	\expandafter\def\csname @seccntfmt@#1\endcsname##1{%
    	\csname the##1\endcsname.\quad
  	}
}
\newcommand{\sectionpunct}[2]{%
  	\expandafter\def\csname @seccntfmt@#1\endcsname##1{%
    	\csname the##1\endcsname#2%
  	}%
}
\renewcommand{\@seccntformat}[1]{\@ifundefined{@seccntfmt@#1}%
  	{\csname the#1\endcsname\quad}% original default style
  	{\csname @seccntfmt@#1\endcsname{#1}}%
}
\sectiondot{section}
\sectiondot{subsection}
\sectiondot{subsubsection}

% References
\renewenvironment{thebibliography}[1]{%
	\baselineskip=16pt plus 2pt minus 1pt
    \section*{\large\refname\@mkboth{\MakeUppercase\refname}{\MakeUppercase\refname}}%
    \addcontentsline{toc}{section}{References}
 	\list{\@biblabel{\@arabic\c@enumiv}}%
    {%
    	\settowidth\labelwidth{\@biblabel{#1}}%
		\leftmargin\labelwidth
		\advance\leftmargin\labelsep
		\@openbib@code
		\usecounter{enumiv}%
		\let\p@enumiv\@empty
		\renewcommand{\theenumiv}{\@arabic\c@enumiv}%
	}%
  	\sloppy
  	\clubpenalty4000
  	\@clubpenalty\clubpenalty
  	\widowpenalty4000%
  	\sfcode`\.\@m
		\catcode`\^^M=10%
		\small
		\parskip-5pt
}

%Appendices
\RequirePackage{appendix}
\renewcommand{\appendixpagename}{\large Appendices}
\renewcommand{\appendixautorefname}{Appendix}
%%% Begin appendix autoref patch for subsections in appendix
\makeatletter
\patchcmd{\hyper@makecurrent}{%
    \ifx\Hy@param\Hy@chapterstring
        \let\Hy@param\Hy@chapapp
    \fi
}{%
    \iftoggle{inappendix}{%true-branch
        \@checkappendixparam{section}%
        \@checkappendixparam{subsection}%
        \@checkappendixparam{subsubsection}%
    }{}%
}{}{\errmessage{failed to patch}}

\newcommand*{\@checkappendixparam}[1]{%
    \def\@checkappendixparamtmp{#1}%
    \ifx\Hy@param\@checkappendixparamtmp
        \let\Hy@param\Hy@appendixstring
    \fi
}
\makeatletter
\newtoggle{inappendix}
\togglefalse{inappendix}
\apptocmd{\appendix}{\toggletrue{inappendix}}{}{\errmessage{failed to patch}}
\apptocmd{\subappendices}{\toggletrue{inappendix}}{}{\errmessage{failed to patch}}
%%% end appendix autoref patch

% Equation, figure, and table numbering
\renewcommand{\theequation}{\thesection.\arabic{equation}}
\@addtoreset{equation}{section}
\renewcommand{\thefigure}{\thesection.\arabic{figure}}
\@addtoreset{figure}{section}
\renewcommand{\thetable}{\thesection.\arabic{table}}
\@addtoreset{table}{section}

%
% Theorem environments
%

\newtheorem{definition}{Definition}
\numberwithin{definition}{section}
\renewcommand{\thedefinition}{\thesection.\arabic{definition}}
\crefname{definition}{Definition}{Definitions}
%
\newaliascnt{lemma}{definition}
\newtheorem{lemma}[lemma]{Lemma}
\aliascntresetthe{lemma}
\crefname{lemma}{Lemma}{Lemmas}
%
\newaliascnt{theorem}{definition}
\newtheorem{theorem}[theorem]{Theorem}
\aliascntresetthe{theorem}
\crefname{theorem}{Theorem}{Theorems}
%
\newaliascnt{observation}{definition}
\newtheorem{observation}[observation]{Observation}
\aliascntresetthe{observation}
\crefname{observation}{Observation}{Observations}
%
\newaliascnt{proposition}{definition}
\newtheorem{proposition}[proposition]{Proposition}
\aliascntresetthe{proposition}
\crefname{proposition}{Proposition}{Propositions}
%
\newaliascnt{question}{definition}
\newtheorem{question}[question]{Question}
\aliascntresetthe{question}
\crefname{question}{Question}{Questions}
%
\newaliascnt{corollary}{definition}
\newtheorem{corollary}[corollary]{Corollary}
\aliascntresetthe{corollary}
\crefname{corollary}{Corollary}{Corollaries}
%
\newaliascnt{remark}{definition}
\newtheorem{remark}[remark]{Remark}
\aliascntresetthe{remark}
\crefname{remark}{Remark}{Remarks}
%
\newaliascnt{example}{definition}
\newtheorem{example}[example]{Example}
\aliascntresetthe{example}
\crefname{example}{Example}{Examples}
%
\newaliascnt{conjecture}{definition}
\newtheorem{conjecture}[conjecture]{Conjecture}
\aliascntresetthe{conjecture}
\crefname{conjecture}{Conjecture}{Conjectures}

%
% Title page
%

\newcommand{\frontpage}{%
	\if@draft
		\begin{center}
			\textbf{\Large\mathversion{bold}\@title}\\
			\today
		\end{center}
		\renewcommand{\thefootnote}{\arabic{footnote}}
	\else
		\setcounter{page}{0}
		\renewcommand{\thefootnote}{\fnsymbol{footnote}}
		\begin{titlepage}
			\@preprintlist
			\vspace*{\if@compression 0\else 1\fi cm}
			\begin{center}
				\textbf{\Large\mathversion{bold}\@title}\\[\if@compression 15pt\else 1cm\fi]
				{\@author}\\[\if@compression 10pt\else 1cm\fi]
				\textbf{Abstract}
				\begin{quote}
					\@abstract
					\if@compression
						% no date
					\else
						\ifdefined\@date
							\vfill\noindent\@date
						\fi
					\fi
				\end{quote}
  			\end{center}
		\end{titlepage}
		\renewcommand{\thefootnote}{\arabic{footnote}}
		\setcounter{footnote}{0}
	\fi
}

%
% Body environment
%

\newif\ifbodyend
\newif\ifbodystart

\newenvironment{body}{%
	\frontpage
	\if@contents
		\tableofcontents
		\bigskip
		\bigskip
		\hrule
		\bigskip
		\bigskip
	\fi
}{%
	\@acknowledgementslist
	\@datalicencemanagementlist
	\IfFileExists{ref/\@references.bib}{
		\bibliographystyle{lib/latexeu}
		\bibliography{ref/\@references}
	}{
		\IfFileExists{\jobname.bbl}{\input{\jobname.bbl}}{}
	}
	\global\bodyendtrue
}