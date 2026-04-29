@echo off
set output_folder=output

for /r %%i in (__pycache__) do (
    if exist "%%i" (
        echo Found directory: %%i
        rd /s /q "%%i"
    )
)

echo clean __pycache__ file done!
