"""Library proof: every practical in the template library, run
through the full engine on synthetic demonstration footage.

Sibling of ``experiments/pendulum_proof`` (which remains the
pendulum's own standing proof). Here the two static practicals get
the same treatment the pendulum got there:

    synthetic demonstration video (known ground truth)
    -> the app's improved colour tracker (coverage recorded)
    -> measured readings table -> the template's own fit
    -> machine design stage (platform, BOM, panel, codegen)
    -> verification through ``mimforge.verification`` with the
       measured table in the demonstration seat

Everything here is synthetic and runs in a Linux VM -- see
README.md for the honesty label.
"""
