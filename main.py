import os
import sys
import re
import csv
from pypdf import PdfReader
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.prompt import Prompt
import math

console = Console()

class ResumeEvaluator:
    def __init__(self, csv_path):
        self.csv_path = csv_path
        self.data = []
        self.load_data()

    def load_data(self):
        try:
            with open(self.csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                # Clean keys (remove potential BOM or whitespace)
                self.data = []
                for row in reader:
                    cleaned_row = {k.strip().replace('\ufeff', ''): v for k, v in row.items() if k}
                    self.data.append(cleaned_row)
        except Exception as e:
            console.print(f"[bold red]Error loading CSV:[/bold red] {e}")
            sys.exit(1)

    def get_unique_jobs(self):
        col_name = 'job_position_name'
        # In case the column name is different, try to find it
        if self.data and col_name not in self.data[0]:
            for k in self.data[0].keys():
                if 'job_position' in k.lower():
                    col_name = k
                    break
        
        jobs = set()
        for row in self.data:
            job = row.get(col_name)
            if job:
                jobs.add(job.strip())
        
        return sorted(list(jobs))

    def get_job_details(self, job_name):
        col_name = 'job_position_name'
        if self.data and col_name not in self.data[0]:
            for k in self.data[0].keys():
                if 'job_position' in k.lower():
                    col_name = k
                    break
                    
        for row in self.data:
            if row.get(col_name) == job_name:
                return {
                    'position': row.get(col_name),
                    'education': str(row.get('educationaL_requirements', '')),
                    'experience': str(row.get('experiencere_requirement', '')),
                    'skills': str(row.get('skills_required', '')),
                    'responsibilities': str(row.get('responsibilities.1', ''))
                }
        return None

    def tokenize(self, text):
        return re.findall(r'\w+', text.lower())

    def calculate_tfidf_score(self, resume_tokens, job_text):
        job_tokens = self.tokenize(job_text)
        job_counts = {}
        for t in job_tokens:
            job_counts[t] = job_counts.get(t, 0) + 1
        
        tfidf_score = 0
        resume_unique = set(resume_tokens)
        for token in resume_unique:
            if token in job_counts:
                tfidf_score += job_counts[token]
        
        max_tfidf_score = sum(job_counts.values())
        
        return tfidf_score, max_tfidf_score

    def evaluate(self, resume_text, job_details):
        if not resume_text or not job_details:
            return None

        rt = resume_text.lower()
        job_text = f"{job_details['education']} {job_details['experience']} {job_details['skills']} {job_details['responsibilities']}".lower()

        resume_tokens = self.tokenize(rt)
        
        # 1. TF-IDF Calculation
        tfidf_score, max_tfidf_score = self.calculate_tfidf_score(resume_tokens, job_text)
        tfidf_ratio = tfidf_score / max_tfidf_score if max_tfidf_score > 0 else 0

        # 2. Keyword Match (Direct Skill check)
        matched_skills = []
        missing_skills = []
        
        skills_raw = job_details['skills']
        if skills_raw and skills_raw.lower() not in ['undefined', 'null', 'nan']:
            # Clean the skills string (it looks like a list string in the CSV)
            skill_list = re.sub(r"[\[\]']", "", skills_raw).split(',')
            skill_list = [s.strip().lower() for s in skill_list if s.strip()]
            
            for skill in skill_list:
                if skill in rt:
                    matched_skills.append(skill)
                else:
                    missing_skills.append(skill)
        
        total_skills = len(matched_skills) + len(missing_skills)
        skill_ratio = len(matched_skills) / total_skills if total_skills > 0 else tfidf_ratio

        # 3. Combined weighted score
        combined_score = (tfidf_ratio * 0.4) + (skill_ratio * 0.6)
        final_score = min(100, round(combined_score * 100 * 1.5))
        
        if final_score < 20 and (len(matched_skills) > 0 or tfidf_score > 0):
            final_score = 20 + round(final_score * 0.8)

        # 4. Recommendations
        recommendations = []
        if missing_skills:
            top_missing = missing_skills[:5]
            recommendations.append(f"Consider adding skills like [bold cyan]{', '.join(top_missing)}[/bold cyan] if you have experience with them.")
        
        if tfidf_ratio < 0.3:
            recommendations.append("Your resume lacks some key terminology used in this job description. Try to mirror the language used in the responsibilities section.")
        
        if len(rt) < 500:
            recommendations.append("Your resume content seems a bit thin. Consider adding more detail about your achievements and projects.")
            
        if not matched_skills and tfidf_ratio > 0.1:
            recommendations.append("You have relevant background, but specific technical skills required for this role are not explicitly mentioned.")

        return {
            'score': final_score,
            'matched_skills': matched_skills,
            'missing_skills': missing_skills,
            'recommendations': recommendations
        }

def get_resume_text(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
        return text
    except Exception as e:
        console.print(f"[bold red]Error reading PDF:[/bold red] {e}")
        return None

def main():
    console.print(Panel.fit("[bold blue]AI Resume Evaluator CLI[/bold blue]", subtitle="Robust Resume Analysis", border_style="blue"))

    # 1. Detect Resume
    files = [f for f in os.listdir('.') if f.endswith('.pdf')]
    if not files:
        console.print("[bold yellow]No PDF resumes found in the current directory.[/bold yellow]")
        console.print("Please place your resume (PDF) in this folder and try again.")
        return

    if len(files) == 1:
        resume_file = files[0]
        console.print(f"Detected resume: [bold green]{resume_file}[/bold green]")
    else:
        resume_file = Prompt.ask("Select a resume to evaluate", choices=files)

    # 2. Extract and Review Resume
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Extracting text from resume...", total=None)
        resume_text = get_resume_text(resume_file)
    
    if not resume_text or not resume_text.strip():
        console.print("[bold red]Failed to extract text from the resume.[/bold red] Ensure the PDF is not an image scan.")
        return

    # Review Step
    console.print(Panel(
        f"[dim]{resume_text[:400]}...[/dim]",
        title="Resume Review (Preview)",
        subtitle="Extracted Content",
        border_style="dim"
    ))
    
    if not Prompt.ask("Does this look correct?", choices=["y", "n"], default="y") == "y":
        console.print("[bold yellow]Evaluation cancelled.[/bold yellow]")
        return

    # 3. Initialize Evaluator & Job Selection
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Loading job dataset...", total=None)
        evaluator = ResumeEvaluator('resume_data.csv')
        jobs = evaluator.get_unique_jobs()

    if not jobs:
        console.print("[bold red]No job positions found in the dataset.[/bold red]")
        return

    # Improved Job Selection (with search)
    selected_job = None
    search_query = ""
    
    while not selected_job:
        if not search_query:
            search_query = Prompt.ask("\nEnter a keyword to search for a job position (e.g. 'Engineer', 'Manager')")
        
        filtered_jobs = [j for j in jobs if search_query.lower() in j.lower()]
        
        if not filtered_jobs:
            console.print(f"[yellow]No jobs found matching '{search_query}'.[/yellow]")
            search_query = ""
            continue
            
        if len(filtered_jobs) > 15:
            console.print(f"[blue]Found {len(filtered_jobs)} matches. Please be more specific.[/blue]")
            search_query = Prompt.ask("Refine your search keyword")
            continue
            
        console.print(f"\n[bold]Matching Job Positions ({len(filtered_jobs)}):[/bold]")
        selected_job = Prompt.ask("Select a position", choices=filtered_jobs + ["Search again"])
        
        if selected_job == "Search again":
            selected_job = None
            search_query = ""

    # 4. Evaluation
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description=f"Evaluating match for {selected_job}...", total=None)
        job_details = evaluator.get_job_details(selected_job)
        analysis = evaluator.evaluate(resume_text, job_details)

    # 5. Display Results
    if analysis:
        score = analysis['score']
        score_color = "green" if score > 75 else "yellow" if score > 45 else "red"
        
        console.print("\n")
        console.print(Panel(
            f"[bold {score_color}]Compatibility Score: {score}%[/bold {score_color}]\n"
            f"[italic]Target Position: {selected_job}[/italic]",
            title="Analysis Report",
            border_style=score_color,
            padding=(1, 2)
        ))

        # Skills Table
        table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        table.add_column("Match Status", style="bold", width=20)
        table.add_column("Skills")
        
        matched_skills = analysis['matched_skills']
        missing_skills = analysis['missing_skills']
        
        if matched_skills:
            table.add_row("[green]✓ Matched[/green]", ", ".join(matched_skills))
        else:
            table.add_row("[yellow]! Matched[/yellow]", "[dim]No specific skills detected[/dim]")
            
        if missing_skills:
            top_missing = missing_skills[:8]
            table.add_row("[red]✗ Missing[/red]", ", ".join(top_missing) + ("..." if len(missing_skills) > 8 else ""))
        
        console.print(table)

        # Recommendations
        if analysis['recommendations']:
            console.print("\n[bold]Expert Recommendations:[/bold]")
            for rec in analysis['recommendations']:
                console.print(f" [blue]•[/blue] {rec}")
        
        console.print(f"\n[bold {score_color}]Final Verdict:[/bold {score_color}] " + 
                      ("Strong Match!" if score > 75 else "Potential Match" if score > 45 else "Low Match - Needs Refinement"))
        console.print("\n[dim]Evaluation complete. Good luck with your application![/dim]\n")
    else:
        console.print("[bold red]Analysis failed.[/bold red]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Aborted by user.[/bold yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred:[/bold red] {e}")
        # Optional: uncomment for debugging
        # import traceback; traceback.print_exc()
        sys.exit(1)
